"""Pipeline orchestration (Phase 7 Part C) -- the demo's actual spine: runs
the full spec pipeline end to end, stage by stage, exactly mirroring the
per-stage CLIs this repo already has (agent/orchestrator/cli.py,
agent/narrative/cli.py, agent/codegen/cli.py) but wired together into one
callable instead of requiring five separate manual invocations.

    resolve URN (MCP search)
      -> assess_change                         (Assessment Engine, Phase 2)
      -> build_narratives                      (Narrative Builder, Phase 3)
      -> decide_migration                      (Decision Engine, Phase 4)
      -> confirm_decision                      (Loop 4 gate #1)
      -> [only if BREAKING and an ORIGIN_HARD_BREAK asset with a
          dbt_file_path exists]:
           copy estate/dbt_project to a temp dir (never the real one)
           -> run_self_correction               (Loop 1, Phase 5)
      -> render_dossier                         (Phase 7 Part A)
      -> create_pr(dry_run=not create_pr_live)  (Phase 7 Part B, Loop 4 gate #2)

`run_full_pipeline` is a plain synchronous function returning a plain dict
(no async, no dataclass) specifically because the task spec says a parallel
Phase 8 watch-mode agent will call it by name via a lazy import:

    from agent.dossier.pipeline import run_full_pipeline
    run_full_pipeline(table, old_column, new_column, change_type)

-- so those four parameter names, in that order, are the one stable external
contract of this module; everything else (the shape of the returned dict,
internal helper names) is free to evolve. Internally it uses `asyncio.run`
to drive the one async stage (MCP URN resolution + assess_change), exactly
like agent/codegen/cli.py's `_run_codegen` does, so callers never need to
know this pipeline touches MCP at all.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path

from agent.assessment.engine import assess_change
from agent.assessment.models import ORIGIN_HARD_BREAK, AssessmentResult, AssetAssessment
from agent.codegen.generator import generate_patch
from agent.decision.engine import decide_migration
from agent.decision.gate import confirm_decision
from agent.decision.models import BREAKING, MigrationDecision
from agent.dossier.pr import create_pr
from agent.dossier.renderer import render_dossier
from agent.loops.reasoning_loop import ReasoningLoop
from agent.loops.self_correction_loop import SelfCorrectionResult, run_self_correction
from agent.narrative.builder import build_narratives
from agent.narrative.llm_client import LLMClient, LLMNotConfigured, build_llm_client
from agent.narrative.models import NarrativeResult
from agent.orchestrator.cli import resolve_dataset_urn
from agent.orchestrator.mcp_client import datahub_mcp_session

REPO_ROOT = Path(__file__).resolve().parents[2]
ESTATE_DBT_PROJECT = REPO_ROOT / "estate" / "dbt_project"


def find_origin_asset(assessment: AssessmentResult) -> AssetAssessment | None:
    """Pure, unit-testable helper: the first ORIGIN_HARD_BREAK asset that
    also has a usable dbt_file_path, or None when there isn't one.

    Deliberately never raises (unlike agent/codegen/cli.py's
    `_find_origin_asset`, which SystemExits when nothing is found) --
    `run_full_pipeline` must degrade gracefully to a code-less dossier
    instead of aborting, since NO_MIGRATION_NEEDED and ADDITIVE decisions
    (and even some BREAKING ones, e.g. a pure-postgres sibling with no local
    dbt model) routinely have no such asset at all.
    """
    for asset in assessment.affected:
        if asset.compile_status == ORIGIN_HARD_BREAK and asset.dbt_file_path:
            return asset
    return None


def _resolve_llm_client() -> LLMClient | None:
    try:
        return build_llm_client()
    except LLMNotConfigured:
        return None


async def _resolve_and_assess(
    table: str,
    old_column: str,
    schema: str,
    platform: str,
    max_hops: int,
    max_tool_calls: int,
) -> AssessmentResult:
    """The one async stage: resolve the table name to a URN via MCP search,
    then run the Assessment Engine. Mirrors agent/codegen/cli.py's
    `_find_origin_asset` -- the MCP session is only open for URN resolution;
    assess_change itself opens/manages its own MCP calls internally."""
    async with datahub_mcp_session() as session:
        resolver_loop = ReasoningLoop(session=session, run_id="resolve")
        changed_urn = await resolve_dataset_urn(resolver_loop, table, platform)

    return await assess_change(
        changed_urn=changed_urn,
        changed_column=old_column,
        source_schema=schema,
        source_table=table,
        max_hops=max_hops,
        max_tool_calls=max_tool_calls,
    )


def _run_codegen_and_verification(
    origin: AssetAssessment,
    old_column: str,
    new_column: str,
    max_attempts: int,
) -> tuple[SelfCorrectionResult, str]:
    """Copies estate/dbt_project to a fresh temp directory -- the same
    temp-copy safety pattern as agent/codegen/cli.py's `_run_codegen` --
    NEVER writes to or runs dbt against the real estate/dbt_project. Builds
    a generate_fn from agent.codegen.generator.generate_patch (+ whatever
    LLM client is configured, falling back to the deterministic template
    when none is) and runs Loop 1 against the temp copy.

    Returns (self_correction_result, pre_patch_original_content) -- the
    latter is read off disk before Loop 1 ever writes to the file, and is
    threaded through to render_dossier so its Generated Code section can
    build a meaningful diff even when self-correction passes on the very
    first attempt (the common case, and the live-verification case).
    """
    temp_root = Path(tempfile.mkdtemp(prefix="blast-radius-pipeline-"))
    project_dir = temp_root / "dbt_project"
    shutil.copytree(ESTATE_DBT_PROJECT, project_dir)

    dbt_file_path = origin.dbt_file_path
    original_content = (project_dir / dbt_file_path).read_text()
    llm_client = _resolve_llm_client()

    def generate_fn(failure_evidence: str | None) -> str:
        return generate_patch(
            old_column=old_column,
            new_column=new_column,
            file_content=original_content,
            failure_evidence=failure_evidence,
            llm_client=llm_client,
        )

    result = run_self_correction(
        dbt_file_path=dbt_file_path,
        project_dir=str(project_dir),
        generate_fn=generate_fn,
        max_attempts=max_attempts,
    )
    return result, original_content


def run_full_pipeline(
    table: str,
    old_column: str,
    new_column: str,
    change_type: str = "rename",
    schema: str = "public",
    platform: str = "postgres",
    auto_approve_decision: bool = False,
    create_pr_live: bool = False,
    max_hops: int = 3,
    max_tool_calls: int = 30,
    max_attempts: int = 3,
) -> dict:
    """Runs the full spec pipeline end to end and returns a summary dict.

    `create_pr_live` is forwarded to `create_pr` as `dry_run=not
    create_pr_live` -- it must always be False in this task (see
    agent/dossier/pr.py's module docstring for the absolute safety rules
    around the True path).

    NO_MIGRATION_NEEDED and ADDITIVE decisions (and BREAKING decisions with
    no ORIGIN_HARD_BREAK asset carrying a usable dbt_file_path) skip codegen
    and PR delivery entirely -- the dossier for those reports only the
    assessment, narrative, and decision sections.

    Returns a dict with these keys:
      - "assessment": AssessmentResult
      - "narrative": NarrativeResult
      - "decision": MigrationDecision (already run through confirm_decision,
            so .confirmation_mode / .human_confirmed / .confirmed_strategy
            are populated)
      - "self_correction": SelfCorrectionResult | None -- None iff codegen
            was skipped (see above)
      - "original_content": str | None -- pre-patch content of the patched
            file, or None iff codegen was skipped
      - "dbt_file_path": str | None -- project-relative path of the patched
            file, or None iff codegen was skipped
      - "dossier_markdown": str -- the full rendered dossier (always
            present, even when nothing was affected)
      - "pr_attempted": bool -- True iff create_pr was called at all (i.e.
            codegen ran); disambiguates "no PR because nothing to patch"
            from "no PR because dry-run returned None" below
      - "pr_result": str | None -- the live PR's URL when create_pr_live is
            True; ALWAYS None when pr_attempted is False, and ALSO None in
            dry-run mode even when pr_attempted is True (create_pr returns
            None and instead prints a preview -- see agent/dossier/pr.py)
      - "branch_name": str | None -- the branch name passed to create_pr, or
            None iff pr_attempted is False
    """
    assessment = asyncio.run(
        _resolve_and_assess(table, old_column, schema, platform, max_hops, max_tool_calls)
    )
    narrative = build_narratives(assessment, changed_table=table)
    decision: MigrationDecision = decide_migration(assessment, change_type=change_type)
    confirm_decision(decision, auto_approve=auto_approve_decision)

    self_correction: SelfCorrectionResult | None = None
    original_content: str | None = None
    dbt_file_path: str | None = None

    if decision.decision_type == BREAKING:
        origin = find_origin_asset(assessment)
        if origin is not None:
            dbt_file_path = origin.dbt_file_path
            self_correction, original_content = _run_codegen_and_verification(
                origin, old_column, new_column, max_attempts
            )

    dossier_markdown = render_dossier(
        assessment=assessment,
        narrative=narrative,
        decision=decision,
        self_correction=self_correction,
        original_content=original_content,
    )

    pr_attempted = False
    pr_result = None
    branch_name = None

    if self_correction is not None and self_correction.attempts:
        pr_attempted = True
        branch_name = f"blast-radius/{table}-{old_column}-to-{new_column}-{uuid.uuid4().hex[:6]}"
        patched_content = self_correction.attempts[-1].candidate_content
        pr_result = create_pr(
            dbt_file_path=dbt_file_path,
            patched_content=patched_content,
            dossier_markdown=dossier_markdown,
            branch_name=branch_name,
            dry_run=not create_pr_live,
            original_content=original_content,
        )

    return {
        "assessment": assessment,
        "narrative": narrative,
        "decision": decision,
        "self_correction": self_correction,
        "original_content": original_content,
        "dbt_file_path": dbt_file_path,
        "dossier_markdown": dossier_markdown,
        "pr_attempted": pr_attempted,
        "pr_result": pr_result,
        "branch_name": branch_name,
    }
