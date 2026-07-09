"""Causal Narrative Builder (spec §3 Stage 2): turns each affected asset's
deterministic facts into plain-English causal prose.

Discipline enforced here: the LLM (or, with no key configured, the template
fallback) only rephrases facts already computed by the Assessment Engine --
evidence strings, compile_status, break_mode, hop, usage_count,
is_dashboard_exposed, owners, select_star_exposure. It never invents a fact.
The prompt states this constraint explicitly and hands over only the asset's
own fields, so there is nothing else in scope for the model to draw from.
"""
from __future__ import annotations

from agent.assessment.models import HARD_BREAK, SILENT_CORRUPTION, UNAFFECTED, AssessmentResult, AssetAssessment
from agent.narrative.llm_client import LLMClient, LLMNotConfigured, build_llm_client
from agent.narrative.models import AssetNarrative, NarrativeResult

SYSTEM_PROMPT = (
    "You are writing one paragraph of a schema-change impact dossier for an "
    "engineering audience. You are given a fixed set of facts about one "
    "downstream data asset, already computed by a deterministic lineage "
    "traversal. Write plain-English causal prose in the house style: state "
    "why the asset breaks (or doesn't), the mechanism (loud compile failure "
    "vs. silent corruption risk), and cite the given evidence inline. "
    "Do not invent any fact not given below -- no file paths, line numbers, "
    "owners, query counts, or hop counts beyond what is listed. If a fact is "
    "not given, do not mention it. Keep it to 2-4 sentences."
)


def _fact_block(asset: AssetAssessment, changed_table: str, changed_column: str) -> str:
    """Renders every fact the LLM is allowed to draw from -- and nothing
    else. This is the enforcement mechanism for "deterministic traversal
    supplies every fact": if a claim isn't derivable from this block, the
    model was told not to make it."""
    lines = [
        f"Changed column: {changed_table}.{changed_column}",
        f"Asset name: {asset.name}",
        f"compile_status: {asset.compile_status}",
        f"break_mode: {asset.break_mode}",
        f"hop: {asset.hop}",
        f"select_star_exposure: {asset.select_star_exposure}",
        f"usage_count (queries on record): {asset.usage_count}",
        f"is_dashboard_exposed: {asset.is_dashboard_exposed}",
        f"owners: {asset.owners or 'none on record'}",
        f"severity_score: {asset.severity_score}",
    ]
    if asset.evidence:
        lines.append("evidence:")
        lines.extend(f"  - {e}" for e in asset.evidence)
    else:
        lines.append("evidence: none on record")
    return "\n".join(lines)


def _template_narrative(asset: AssetAssessment, changed_table: str, changed_column: str) -> str:
    """Deterministic fallback prose, built purely from string formatting over
    the same facts the LLM prompt receives -- used when no LLM API key is
    configured. Still readable, still fact-only, just less fluent.

    The break_mode/select_star_exposure combination matters here, not just
    break_mode alone: an asset can be a *loud* break today (compile_status is
    a hard break) while also carrying a `SELECT *` that would make a careless
    fix a *silent* one -- exactly the fct_revenue case in spec §3's own
    example ("this break is loud. However... a wrong patch here would break
    silently."). Both halves of that story are real facts on the asset, so
    both get stated.
    """
    subject = f"`{asset.name}`"
    hop_note = f" (hop {asset.hop} from the changed table)" if asset.hop is not None else ""

    if asset.compile_status == "ORIGIN_HARD_BREAK":
        cause = f"{subject} breaks because it directly references the changed column `{changed_column}` on `{changed_table}`"
    elif asset.compile_status == "CASCADE_HARD_BREAK":
        cause = f"{subject} breaks because an upstream dependency in its lineage fails first"
    else:
        cause = f"{subject} is unaffected -- it does not read the changed column"

    if asset.break_mode == HARD_BREAK:
        mechanism = "This break is loud: dbt compilation or execution fails outright."
        if asset.select_star_exposure:
            mechanism += (
                f" However, {subject} also expands an upstream table via `SELECT *` -- "
                "a wrong patch here would break silently instead, with columns "
                "shifting rather than the query failing to compile."
            )
    elif asset.break_mode == SILENT_CORRUPTION:
        mechanism = (
            "This is a silent-corruption risk, not a loud break: it expands an upstream "
            "table via `SELECT *` with no compile-time failure, so a wrong patch could "
            "ship undetected."
        )
    else:
        mechanism = "No downstream impact from this change was found."

    exposure_bits = []
    if asset.is_dashboard_exposed:
        exposure_bits.append("it feeds a dashboard")
    if asset.usage_count:
        unit = "query" if asset.usage_count == 1 else "queries"
        exposure_bits.append(f"{asset.usage_count} recorded {unit} against it")
    exposure = (" " + "; ".join(exposure_bits).capitalize() + ".") if exposure_bits else ""

    evidence = " Evidence: " + "; ".join(asset.evidence) + "." if asset.evidence else ""

    return f"{cause}{hop_note}. {mechanism}{exposure}{evidence}"


def _build_one(
    asset: AssetAssessment, changed_table: str, changed_column: str, llm_client: LLMClient | None
) -> AssetNarrative:
    text = None
    source = "template"

    if llm_client is not None:
        try:
            user_prompt = _fact_block(asset, changed_table, changed_column)
            generated = llm_client.generate(SYSTEM_PROMPT, user_prompt)
            # An empty-string response is not None, so a bare `is None` check
            # would ship narrative_text="" mislabeled source="llm" instead of
            # falling back to the template below -- treat blank the same as
            # a failed call.
            if generated is not None and generated.strip():
                text = generated
                source = "llm"
        except Exception:
            # A runtime failure (rate limit, network, transient API error)
            # shouldn't lose the whole dossier over one asset -- fall back to
            # the template for this asset just like the no-key path does.
            text = None

    if text is None:
        text = _template_narrative(asset, changed_table, changed_column)
        source = "template"

    return AssetNarrative(
        urn=asset.urn,
        name=asset.name,
        narrative_text=text,
        evidence_cited=list(asset.evidence),
        break_mode=asset.break_mode,
        source=source,
    )


def build_narratives(
    result: AssessmentResult,
    changed_table: str,
    llm_client: LLMClient | None = None,
) -> NarrativeResult:
    """Builds one causal narrative per affected asset (spec §3 Stage 2).

    UNAFFECTED assets are excluded from `narratives` -- they don't have a
    causal story to tell -- but are summarized in one line via
    `safe_summary`, since telling users what's *safe* is half the value
    (spec §3 Stage 1, §5 item 1).

    If `llm_client` is not given, one is built from `LLM_PROVIDER`/env. If
    that provider has no API key configured, every narrative falls back to
    the deterministic template rather than raising or hanging -- required
    for the demo (no key is configured in this project) and for tests to run
    without live API access.
    """
    resolved_client: LLMClient | None = llm_client
    if resolved_client is None:
        try:
            resolved_client = build_llm_client()
        except LLMNotConfigured:
            resolved_client = None

    narratives = [
        _build_one(asset, changed_table, result.changed_column, resolved_client) for asset in result.affected
    ]

    unaffected = [a for a in result.scanned if a.break_mode == UNAFFECTED]
    safe_summary = None
    if unaffected:
        names = ", ".join(sorted(a.name for a in unaffected))
        safe_summary = f"Confirmed safe -- unaffected by this change: {names}."

    return NarrativeResult(
        changed_urn=result.changed_urn,
        changed_column=result.changed_column,
        narratives=narratives,
        safe_summary=safe_summary,
    )
