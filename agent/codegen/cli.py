"""Standalone codegen CLI (Phase 5).

    python -m agent.codegen.cli --table raw_customers --old-column cust_id --new-column customer_id

Kept as its own entry point rather than extending
agent/orchestrator/cli.py's `assess` subcommand, mirroring
agent/narrative/cli.py -- this module only *imports* from
agent/orchestrator/cli.py (`resolve_dataset_urn`, read-only) rather than
modifying it.

Internally: resolve table -> URN via MCP search, run the Assessment Engine
(assess_change) to find the ORIGIN_HARD_BREAK asset, copy estate/dbt_project
to a fresh temp directory, then run Loop 1 (agent.loops.self_correction_loop
.run_self_correction) against that temp copy using a real generate_fn built
from agent.codegen.generator.generate_patch + the shared, provider-
configurable LLM client. NEVER writes to or runs dbt against the real
estate/dbt_project -- only the temp copy is touched, and this phase only
prints the result; landing the patch back into estate/ is a later delivery
phase.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from agent.assessment.engine import assess_change
from agent.assessment.models import ORIGIN_HARD_BREAK, AssetAssessment
from agent.codegen.generator import generate_patch
from agent.loops.reasoning_loop import ReasoningLoop
from agent.loops.self_correction_loop import SelfCorrectionResult, run_self_correction
from agent.narrative.llm_client import LLMClient, LLMNotConfigured, build_llm_client
from agent.orchestrator.cli import resolve_dataset_urn
from agent.orchestrator.mcp_client import datahub_mcp_session

REPO_ROOT = Path(__file__).resolve().parents[2]
ESTATE_DBT_PROJECT = REPO_ROOT / "estate" / "dbt_project"


def render_result(result: SelfCorrectionResult) -> str:
    lines = [f"SELF-CORRECTION -- {result.dbt_file_path}  (run {result.run_id})", ""]
    for attempt in result.attempts:
        verification = attempt.verification
        status = "PASS" if verification.passed else "FAIL"
        lines.append(f"attempt {attempt.attempt_number}: {status}")
        for outcome in verification.outcomes:
            mark = "ok" if outcome.passed else "FAIL"
            lines.append(f"  [{outcome.level}] {mark} -- {outcome.message}")
            if not outcome.passed and outcome.raw_error:
                lines.append(f"    raw_error: {outcome.raw_error}")
        lines.append("")
    lines.append(f"final_status: {result.final_status}")
    if result.final_status == "PASSED" and result.attempts:
        lines.append("")
        lines.append("FINAL CANDIDATE SQL:")
        lines.append(result.attempts[-1].candidate_content)
    return "\n".join(lines)


async def _find_origin_asset(args: argparse.Namespace) -> AssetAssessment:
    async with datahub_mcp_session() as session:
        resolver_loop = ReasoningLoop(session=session, run_id="resolve")
        changed_urn = await resolve_dataset_urn(resolver_loop, args.table, args.platform)

    assessment = await assess_change(
        changed_urn=changed_urn,
        changed_column=args.old_column,
        source_schema=args.schema,
        source_table=args.table,
        max_hops=args.max_hops,
        max_tool_calls=args.max_tool_calls,
    )

    origin_assets = [a for a in assessment.affected if a.compile_status == ORIGIN_HARD_BREAK]
    if not origin_assets:
        raise SystemExit("No ORIGIN_HARD_BREAK asset found for this change -- nothing to patch.")
    if len(origin_assets) > 1:
        names = ", ".join(a.name for a in origin_assets)
        print(
            f"warning: {len(origin_assets)} ORIGIN_HARD_BREAK assets found ({names}) -- patching the first.",
            file=sys.stderr,
        )

    origin = origin_assets[0]
    if not origin.dbt_file_path:
        raise SystemExit(f"ORIGIN_HARD_BREAK asset '{origin.name}' has no dbt_file_path -- cannot generate a patch.")
    return origin


def _resolve_llm_client() -> LLMClient | None:
    try:
        return build_llm_client()
    except LLMNotConfigured:
        return None


def make_generate_fn(original_content: str, old_column: str, new_column: str, llm_client: LLMClient | None):
    """Builds the `generate_fn` closure Loop 1 calls once per attempt: fixed
    old/new column names and the origin file's pristine original content,
    varying only the failure_evidence argument across retries."""

    def generate_fn(failure_evidence: str | None) -> str:
        return generate_patch(
            old_column=old_column,
            new_column=new_column,
            file_content=original_content,
            failure_evidence=failure_evidence,
            llm_client=llm_client,
        )

    return generate_fn


async def _run_codegen(args: argparse.Namespace) -> None:
    origin = await _find_origin_asset(args)
    dbt_file_path = origin.dbt_file_path
    print(f"ORIGIN_HARD_BREAK asset: {origin.name}  ({dbt_file_path})")

    temp_root = Path(tempfile.mkdtemp(prefix="blast-radius-codegen-"))
    project_dir = temp_root / "dbt_project"
    shutil.copytree(ESTATE_DBT_PROJECT, project_dir)
    print(f"Working copy (never the real estate/dbt_project): {project_dir}")
    print()

    original_content = (project_dir / dbt_file_path).read_text()
    llm_client = _resolve_llm_client()
    print(f"LLM client: {'configured (' + llm_client.provider + ')' if llm_client else 'not configured -- using deterministic template fallback'}")
    print()

    generate_fn = make_generate_fn(original_content, args.old_column, args.new_column, llm_client)

    result = run_self_correction(
        dbt_file_path=dbt_file_path,
        project_dir=str(project_dir),
        generate_fn=generate_fn,
        max_attempts=args.max_attempts,
    )

    print(render_result(result))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="blast-radius-codegen")
    parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    parser.add_argument("--old-column", required=True, dest="old_column", help="Column being renamed away from, e.g. cust_id")
    parser.add_argument("--new-column", required=True, dest="new_column", help="Column being renamed to, e.g. customer_id")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--platform", default="postgres")
    parser.add_argument("--max-hops", dest="max_hops", type=int, default=3)
    parser.add_argument("--max-tool-calls", dest="max_tool_calls", type=int, default=30)
    parser.add_argument("--max-attempts", dest="max_attempts", type=int, default=3)

    args = parser.parse_args(argv)
    asyncio.run(_run_codegen(args))


if __name__ == "__main__":
    main(sys.argv[1:])
