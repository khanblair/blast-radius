"""Loop 4 gate #1: human confirmation of the recommended migration strategy
(spec §3 Stage 3, §4 Loop 4). There is no web UI in this project's MVP scope
(explicitly deferred), so this is the CLI-based substitute: render the full
decision -- rationale, options with trade-offs, rejected alternatives with
reasons -- then either accept it non-interactively (`--auto-approve`,
required so the demo and automated tests never block on stdin) or prompt a
human to accept the recommendation or override it with another listed
strategy.

Kept separate from `agent/orchestrator/cli.py` (which only renders and calls
into this module) so this logic -- the part the task asks to be unit-tested
with both `--auto-approve` and a mocked interactive prompt -- stays testable
without importing the CLI module a parallel Narrative Builder phase is also
editing.
"""
from __future__ import annotations

from typing import Callable

from agent.decision.models import AUTO_APPROVED, HUMAN_CONFIRMED, NOT_APPLICABLE, MigrationDecision


def render_decision(decision: MigrationDecision) -> str:
    """Renders the full "Migration Decision" block (spec §5, dossier item 4)
    as plain text: decision type, rationale, every option with its
    trade-off, which one is recommended, and the rejected alternatives with
    reasons."""
    lines = [f"MIGRATION DECISION -- {decision.decision_type}", "", decision.rationale]

    if decision.options:
        lines.append("")
        lines.append("OPTIONS:")
        for opt in decision.options:
            marker = " (RECOMMENDED)" if opt.strategy_id == decision.recommended_strategy else ""
            lines.append(f"  {opt.strategy_id}. {opt.name}{marker}")
            lines.append(f"     {opt.description}")
            lines.append(f"     Trade-off: {opt.tradeoffs}")

    if decision.rejected:
        lines.append("")
        lines.append("REJECTED:")
        for rej in decision.rejected:
            lines.append(f"  {rej.strategy_id}: {rej.reason}")

    return "\n".join(lines)


def confirm_decision(
    decision: MigrationDecision,
    auto_approve: bool,
    input_fn: Callable[[str], str] = input,
) -> MigrationDecision:
    """Applies Loop 4 gate #1 to `decision` in place and returns it.

    Records not just *whether* the decision was confirmed but *how*
    (`confirmation_mode`): a trust-focused tool must never claim a human
    signed off on something nobody was actually asked about, so
    `human_confirmed` is only ever True for the real interactive path --
    `--auto-approve` is recorded as a policy bypass, not a fabricated human
    sign-off.

    `input_fn` is injectable so tests can simulate stdin without blocking on
    real input().
    """
    if decision.recommended_strategy is None:
        # NO_MIGRATION_NEEDED / ADDITIVE -- there is no strategy to choose
        # between, so there is nothing to confirm. Gate is a no-op.
        decision.confirmation_mode = NOT_APPLICABLE
        decision.human_confirmed = False
        decision.confirmed_strategy = None
        return decision

    if auto_approve:
        decision.confirmation_mode = AUTO_APPROVED
        decision.human_confirmed = False
        decision.confirmed_strategy = decision.recommended_strategy
        return decision

    valid_ids = sorted({opt.strategy_id for opt in decision.options})
    prompt = (
        f"\nConfirm recommended strategy [{decision.recommended_strategy}], or type one of "
        f"{valid_ids} to override (blank = accept recommendation): "
    )
    answer = input_fn(prompt).strip().upper()
    chosen = answer if answer in valid_ids else decision.recommended_strategy

    decision.confirmation_mode = HUMAN_CONFIRMED
    decision.human_confirmed = True
    decision.confirmed_strategy = chosen
    return decision
