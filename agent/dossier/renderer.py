"""Dossier renderer (spec Stage 6, "Deliver").

Renders a single markdown document combining the outputs of every earlier
stage -- Assessment (Phase 2), Narrative (Phase 3), Decision (Phase 4), and
Loop 1 self-correction (Phase 5) -- into the one artifact a human reviews
before a change lands (spec's "trust narrative": show your work, don't just
claim an answer).

Kept import-light on purpose: this module only imports the plain dataclass
model contracts (agent.assessment.models / agent.narrative.models /
agent.decision.models / agent.loops.self_correction_loop) plus stdlib
`difflib` -- no MCP, no dbt, no network -- so its own tests run in isolation
and fast, and so agent/dossier/pr.py (which also wants to stay import-light)
never has to pull in the heavier pipeline machinery just to render a preview.
"""
from __future__ import annotations

import difflib

from agent.assessment.models import AssessmentResult
from agent.decision.models import AUTO_APPROVED, BREAKING, HUMAN_CONFIRMED, MigrationDecision
from agent.loops.self_correction_loop import PASSED, SelfCorrectionResult
from agent.narrative.models import NarrativeResult


def _render_impact_assessment(assessment: AssessmentResult) -> str:
    """Markdown rendering of the severity matrix -- same facts/ordering as
    agent/orchestrator/cli.py's render_summary (text), reshaped as a
    markdown table so it reads well in a PR body / static viewer."""
    distinct_owners = {owner for asset in assessment.affected for owner in asset.owners}
    lines = [
        "## 1. Impact Assessment",
        "",
        f"**Changed:** `{assessment.changed_urn}` column `{assessment.changed_column}`",
        "",
        f"- Scanned: {len(assessment.scanned)}",
        f"- Affected: {len(assessment.affected)}",
        f"- Hard breaks: {assessment.hard_break_count}",
        f"- Silent-corruption risks: {assessment.silent_corruption_count}",
        f"- Confirmed safe: {assessment.unaffected_count}",
        f"- Distinct owners affected: {len(distinct_owners)}",
        f"- Deepest hop: {assessment.deepest_hop}",
        "",
        "### Severity matrix (ranked)",
        "",
        "| Severity | Asset | Break mode | Hop | Usage | Dashboard exposed |",
        "|---:|---|---|---:|---:|---|",
    ]
    for asset in assessment.scanned:
        lines.append(
            f"| {asset.severity_score:.1f} | {asset.name} | {asset.break_mode} | "
            f"{asset.hop} | {asset.usage_count} | {asset.is_dashboard_exposed} |"
        )
        for e in asset.evidence:
            lines.append(f"|  |  | evidence: `{e}` |  |  |  |")
    return "\n".join(lines)


def _render_causal_narratives(narrative: NarrativeResult) -> str:
    """Markdown rendering of the causal narratives -- style reference is
    agent/narrative/cli.py's render_narratives."""
    lines = [
        "## 2. Causal Narratives",
        "",
        f"**Changed:** `{narrative.changed_urn}` column `{narrative.changed_column}`",
        "",
    ]
    if not narrative.narratives:
        lines.append("_No affected assets to narrate._")
    for n in narrative.narratives:
        lines.append(f"### [{n.break_mode}] {n.name}  _(source: {n.source})_")
        lines.append("")
        lines.append(n.narrative_text)
        if n.evidence_cited:
            lines.append("")
            lines.append("Evidence cited:")
            for e in n.evidence_cited:
                lines.append(f"- `{e}`")
        lines.append("")
    if narrative.safe_summary:
        lines.append(f"_{narrative.safe_summary}_")
    return "\n".join(lines)


def _render_migration_decision(decision: MigrationDecision) -> str:
    """Markdown rendering of the migration decision -- style reference is
    agent/decision/gate.py's render_decision, extended (beyond that text
    reference) with confirmation_mode/human_confirmed, which render_decision
    itself never prints -- the dossier is the one place that provenance must
    be visible."""
    lines = [
        f"## 3. Migration Decision -- {decision.decision_type}",
        "",
        decision.rationale,
    ]

    if decision.options:
        lines.append("")
        lines.append("### Options")
        for opt in decision.options:
            marker = " **(RECOMMENDED)**" if opt.strategy_id == decision.recommended_strategy else ""
            lines.append(f"- **{opt.strategy_id}. {opt.name}**{marker}")
            lines.append(f"  - {opt.description}")
            lines.append(f"  - Trade-off: {opt.tradeoffs}")

    if decision.rejected:
        lines.append("")
        lines.append("### Rejected alternatives")
        for rej in decision.rejected:
            lines.append(f"- **{rej.strategy_id}**: {rej.reason}")

    lines.append("")
    lines.append("### Confirmation")
    if decision.confirmation_mode == HUMAN_CONFIRMED:
        confirmation_line = (
            f"Human-confirmed -- strategy **{decision.confirmed_strategy}** (human_confirmed=True)"
        )
    elif decision.confirmation_mode == AUTO_APPROVED:
        confirmation_line = (
            f"Auto-approved (policy bypass, NOT a human sign-off) -- strategy "
            f"**{decision.confirmed_strategy}** (human_confirmed=False)"
        )
    else:
        confirmation_line = "Not applicable -- no strategy to confirm (human_confirmed=False)"
    lines.append(f"- confirmation_mode: `{decision.confirmation_mode}`")
    lines.append(f"- human_confirmed: `{decision.human_confirmed}`")
    lines.append(f"- {confirmation_line}")

    return "\n".join(lines)


def _diff_block(before: str, after: str, fromfile: str, tofile: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
    if not diff_lines:
        return "_No textual difference._"
    diff_text = "".join(diff_lines)
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    return f"```diff\n{diff_text}```"


def _render_generated_code(self_correction: SelfCorrectionResult, original_content: str | None) -> str:
    """Unified diff between the FIRST attempt's candidate and the LAST
    attempt's candidate. When there's only one attempt, diffs that single
    candidate against the pre-patch `original_content` instead (when given)
    so the actual change is visible rather than just the final state with
    nothing to compare it to."""
    lines = ["## 4. Generated Code", "", f"File: `{self_correction.dbt_file_path}`", ""]

    if not self_correction.attempts:
        lines.append("_No attempts were made._")
        return "\n".join(lines)

    first_attempt = self_correction.attempts[0]
    last_attempt = self_correction.attempts[-1]

    if len(self_correction.attempts) >= 2:
        lines.append(f"Diff: attempt 1 -> attempt {last_attempt.attempt_number} (final).")
        lines.append("")
        lines.append(
            _diff_block(
                first_attempt.candidate_content,
                last_attempt.candidate_content,
                fromfile=f"{self_correction.dbt_file_path} (attempt 1)",
                tofile=f"{self_correction.dbt_file_path} (attempt {last_attempt.attempt_number})",
            )
        )
    elif original_content is not None:
        lines.append("Diff: pre-patch original -> attempt 1 (only attempt).")
        lines.append("")
        lines.append(
            _diff_block(
                original_content,
                first_attempt.candidate_content,
                fromfile=f"{self_correction.dbt_file_path} (original)",
                tofile=f"{self_correction.dbt_file_path} (attempt 1)",
            )
        )
    else:
        lines.append(
            "_Only one attempt was made and no pre-patch original_content was supplied -- "
            "showing the final candidate in full instead of a diff._"
        )
        lines.append("")
        lines.append(f"```sql\n{first_attempt.candidate_content}\n```")

    return "\n".join(lines)


def _render_verification_gauntlet(self_correction: SelfCorrectionResult) -> str:
    """Every attempt's per-level pass/fail, and on any failure the
    raw_error that triggered the next retry -- the part of the dossier that
    makes the self-correction loop's work auditable."""
    lines = ["## 5. Verification Gauntlet", ""]
    for attempt in self_correction.attempts:
        verification = attempt.verification
        status = "PASS" if verification.passed else "FAIL"
        lines.append(f"### Attempt {attempt.attempt_number}: {status}")
        for outcome in verification.outcomes:
            mark = "PASS" if outcome.passed else "FAIL"
            lines.append(f"- `[{outcome.level}]` **{mark}** -- {outcome.message}")
            if not outcome.passed and outcome.raw_error:
                lines.append("  ```")
                lines.append(f"  {outcome.raw_error}")
                lines.append("  ```")
        lines.append("")
    lines.append(f"**final_status: {self_correction.final_status}**")
    return "\n".join(lines)


def render_dossier(
    assessment: AssessmentResult,
    narrative: NarrativeResult,
    decision: MigrationDecision,
    self_correction: SelfCorrectionResult | None = None,
    original_content: str | None = None,
) -> str:
    """Renders the full dossier as one markdown document.

    `self_correction` is optional (default None): the NO_MIGRATION_NEEDED and
    ADDITIVE decision types run no codegen at all (agent/dossier/pipeline.py
    skips Loop 1 entirely for those), so there is nothing to pass -- in that
    case sections 4 ("Generated Code") and 5 ("Verification Gauntlet") are
    omitted rather than fabricated. A BREAKING decision with no
    self_correction (Strategy C, defer) is a distinct case from those two --
    a fix genuinely IS needed, just deliberately not generated pending owner
    sign-off -- so its banner must not claim "no code change required."

    `original_content` is the pre-patch content of the file self_correction
    touched, used only to build a meaningful diff for section 4 when there
    was exactly one attempt (see _render_generated_code) -- Loop 1 itself
    doesn't carry this around, so callers (agent/dossier/pipeline.py) that
    have it on hand (they read it off disk before calling run_self_correction,
    mirroring agent/codegen/cli.py's `_run_codegen`) pass it through here.

    The header prominently states final_status: PASSED dossiers read as a
    delivery ("ready"), NEEDS_HUMAN dossiers read as a distinct, visually
    different request for help ("stopped, needs a human") -- never the same
    banner with a different word swapped in, since a NEEDS_HUMAN outcome
    must never look like something safe to merge on autopilot.
    """
    lines = [f"# Blast Radius Dossier -- {assessment.changed_urn} column `{assessment.changed_column}`", ""]

    if self_correction is None and decision.decision_type == BREAKING:
        lines.append("> **STATUS: DEFERRED -- A FIX IS NEEDED, BUT NOT GENERATED YET**")
        lines.append(
            f"> Decision: BREAKING, strategy {decision.recommended_strategy} (see section 3). "
            "No codegen or verification was run -- see the rationale below before generating one."
        )
    elif self_correction is None:
        lines.append("> **STATUS: ASSESSMENT ONLY -- NO CODE CHANGE REQUIRED**")
        lines.append(f"> Decision: {decision.decision_type}. No codegen or verification was run.")
    elif self_correction.final_status == PASSED:
        lines.append("> ## STATUS: PASSED -- READY FOR REVIEW")
        lines.append(">")
        lines.append(
            f"> All verification levels passed after {len(self_correction.attempts)} attempt(s). "
            "The generated patch below is ready to deliver."
        )
    else:
        lines.append("> ## STATUS: NEEDS_HUMAN -- **NOT A DELIVERY, THIS IS A REQUEST FOR HELP**")
        lines.append(">")
        lines.append(
            f"> Self-correction exhausted {len(self_correction.attempts)} attempt(s) without passing "
            "verification. Do NOT merge the candidate below as-is -- a human needs to "
            "look at the Verification Gauntlet (section 5) and finish this by hand."
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append(_render_impact_assessment(assessment))
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append(_render_causal_narratives(narrative))
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append(_render_migration_decision(decision))
    lines.append("")

    if self_correction is not None:
        lines.append("---")
        lines.append("")
        lines.append(_render_generated_code(self_correction, original_content))
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(_render_verification_gauntlet(self_correction))
        lines.append("")

    return "\n".join(lines)
