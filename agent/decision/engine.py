"""Migration Decision Engine (spec §3 Stage 3): decides, deterministically,
whether a declared change needs a migration at all and -- if it does -- which
of three fixed strategies to recommend.

No LLM anywhere in this module. Per the project's "no freeform reasoning,
every loop has a cap/exit/trace" discipline, this is a rules/heuristics
engine: every branch is derived from `AssessmentResult` data (already
computed by Phase 2's deterministic traversal) or the declared `change_type`,
never guessed. Given the same inputs, `decide_migration` always returns the
same `MigrationDecision`.
"""
from __future__ import annotations

from agent.assessment.models import AssessmentResult
from agent.decision.models import (
    ADDITIVE,
    BREAKING,
    NO_MIGRATION_NEEDED,
    MigrationDecision,
    RejectedStrategy,
    StrategyOption,
)

# --- Declared change types --------------------------------------------------
CHANGE_RENAME = "rename"
CHANGE_ADD_COLUMN = "add_column"
CHANGE_WIDEN_TYPE = "widen_type"
CHANGE_DROP_COLUMN = "drop_column"

# Only these are non-breaking *by construction*: a new nullable column or a
# lossless type widening cannot invalidate an existing consumer's query, no
# matter how large the blast radius looks. "rename" and "drop_column" always
# remove or rename something a consumer might depend on, so they can never
# resolve to ADDITIVE regardless of what the traversal finds.
ADDITIVE_CHANGE_TYPES = frozenset({CHANGE_ADD_COLUMN, CHANGE_WIDEN_TYPE})

# --- BREAKING recommendation thresholds -------------------------------------
# Tunable, module-level, and deliberately conservative for a small hackathon
# estate. The canonical demo scenario (3 hard breaks, deepest affected hop 2,
# fct_revenue dashboard-exposed) must land on Strategy B *without* hardcoding
# B -- these constants are what makes that fall out of the general rule
# below instead of being forced.
#
# C (defer & deprecate) fires only when the blast radius itself is the risk --
# rushing a same-day fix across this much surface area would be the more
# dangerous move than waiting for a deprecation cycle. ">" on hard-break
# count and ">=" on hop depth are deliberately picked so the canonical
# scenario's 3 breaks / hop 2 sits comfortably below both and never trips
# this branch by accident.
DEFER_HARD_BREAK_THRESHOLD = 5   # more than this many HARD_BREAK assets -> recommend C
DEFER_DEEPEST_HOP_THRESHOLD = 4  # affected-asset hop reaching this depth -> recommend C

# B (bridge migration) fires whenever *any* affected asset is dashboard-
# exposed: a human looks at a dashboard directly, so a one-shot cutover
# risks a visible, embarrassing break instead of a quiet, gradual patch.
# (No separate constant needed -- this is a boolean condition, not a
# magnitude threshold, so it lives directly in the branch below.)


def _base_options() -> list[StrategyOption]:
    """The three fixed strategies, spec §3 Stage 3. Descriptions and
    trade-offs are constant text; only the recommendation and rejections
    vary per assessment."""
    return [
        StrategyOption(
            strategy_id="A",
            name="Direct patch",
            description="Patch every consumer in one PR.",
            tradeoffs="Clean and atomic, but big-bang risk.",
        ),
        StrategyOption(
            strategy_id="B",
            name="Bridge migration",
            description=(
                "Add a compatibility view aliasing old -> new, patch consumers "
                "gradually, remove the bridge later."
            ),
            tradeoffs="Zero-downtime and gradual, but more moving parts and a cleanup step you can forget.",
        ),
        StrategyOption(
            strategy_id="C",
            name="Defer & deprecate",
            description=(
                "Blast radius is too large/risky to fix now; recommend a "
                "deprecation cycle with owner sign-off instead of an immediate fix."
            ),
            tradeoffs="Avoids a risky rushed fix, but doesn't solve the problem today.",
        ),
    ]


def _affected_deepest_hop(result: AssessmentResult) -> int:
    """Deepest hop among *affected* assets only -- not `result.deepest_hop`,
    which spans every scanned asset including confirmed-safe ones. A deep but
    unaffected asset carries no migration risk and must not inflate the
    defer signal."""
    hops = [a.hop for a in result.affected if a.hop is not None]
    return max(hops, default=0)


def _recommend_defer(result: AssessmentResult, deepest_affected_hop: int) -> tuple[str, str, list[RejectedStrategy]]:
    rationale = (
        f"{result.hard_break_count} hard break(s) across a lineage chain reaching affected hop "
        f"{deepest_affected_hop} exceed the bar for a same-day fix "
        f"(> {DEFER_HARD_BREAK_THRESHOLD} hard breaks or affected hop >= {DEFER_DEEPEST_HOP_THRESHOLD}) -- "
        "recommend deferring to a deprecation cycle with owner sign-off rather than rushing "
        "a patch across this much surface area."
    )
    rejected = [
        RejectedStrategy(
            "A",
            f"Direct patch rejected: would require touching all {result.hard_break_count} hard breaks "
            "in a single PR -- too much simultaneous surface area to land safely.",
        ),
        RejectedStrategy(
            "B",
            f"Bridge migration rejected: a bridge still requires patching every consumer eventually "
            f"across a chain this deep (affected hop {deepest_affected_hop}); the risk is the size and "
            "depth of the blast radius itself, which a bridge doesn't shrink.",
        ),
    ]
    return "C", rationale, rejected


def _recommend_bridge(result: AssessmentResult, dashboard_exposed_names: list[str]) -> tuple[str, str, list[RejectedStrategy]]:
    plural = len(dashboard_exposed_names) != 1
    rationale = (
        f"{', '.join(dashboard_exposed_names)} {'are' if plural else 'is'} dashboard-exposed -- a "
        "one-shot cutover risks a visible break for someone looking at a dashboard directly. "
        "Recommend a compatibility bridge so consumers migrate gradually instead."
    )
    rejected = [
        RejectedStrategy(
            "A",
            f"Direct patch rejected: {', '.join(dashboard_exposed_names)} {'are' if plural else 'is'} "
            "dashboard-exposed, so a big-bang patch risks a visible break there before every consumer "
            "is updated.",
        ),
        RejectedStrategy(
            "C",
            f"Defer & deprecate rejected: blast radius ({result.hard_break_count} hard break(s)) is "
            "not large or deep enough to justify delaying a fix that a bridge can deliver safely now.",
        ),
    ]
    return "B", rationale, rejected


def _recommend_direct_patch(result: AssessmentResult, deepest_affected_hop: int) -> tuple[str, str, list[RejectedStrategy]]:
    rationale = (
        f"Blast radius is small ({result.hard_break_count} hard break(s), deepest affected hop "
        f"{deepest_affected_hop}) and no affected consumer is dashboard-exposed -- recommend patching "
        "every consumer directly in one PR."
    )
    rejected = [
        RejectedStrategy(
            "B",
            "Bridge migration rejected: no affected consumer is dashboard-exposed or otherwise "
            "high-exposure enough to justify the bridge's extra moving parts and cleanup step.",
        ),
        RejectedStrategy(
            "C",
            f"Defer & deprecate rejected: blast radius ({result.hard_break_count} hard break(s), "
            f"deepest affected hop {deepest_affected_hop}) is small enough to patch directly without "
            "deferring.",
        ),
    ]
    return "A", rationale, rejected


def _decide_breaking(result: AssessmentResult) -> MigrationDecision:
    options = _base_options()
    deepest_affected_hop = _affected_deepest_hop(result)
    dashboard_exposed_names = [a.name for a in result.affected if a.is_dashboard_exposed]

    # Precedence: a blast radius large/deep enough to defer is a bigger risk
    # than exposure alone, so C is checked before B -- if both conditions
    # hold, deferring the whole thing beats a bridge that still has to patch
    # every consumer eventually.
    if result.hard_break_count > DEFER_HARD_BREAK_THRESHOLD or deepest_affected_hop >= DEFER_DEEPEST_HOP_THRESHOLD:
        recommended, rationale, rejected = _recommend_defer(result, deepest_affected_hop)
    elif dashboard_exposed_names:
        recommended, rationale, rejected = _recommend_bridge(result, dashboard_exposed_names)
    else:
        recommended, rationale, rejected = _recommend_direct_patch(result, deepest_affected_hop)

    return MigrationDecision(
        decision_type=BREAKING,
        rationale=rationale,
        options=options,
        recommended_strategy=recommended,
        rejected=rejected,
    )


def decide_migration(result: AssessmentResult, change_type: str = CHANGE_RENAME) -> MigrationDecision:
    """Pure Stage 3 decision logic -- no I/O, no LLM, fully unit-testable
    against fabricated `AssessmentResult`s. Given the same `result` and
    `change_type`, always returns the same `MigrationDecision`.
    """
    if not result.affected:
        # Checked first, unconditionally: if truly nothing downstream
        # references the changed column, that's true regardless of what kind
        # of change was declared -- there's nothing left to weigh options
        # against, so this branch wins even for a nominally "additive"
        # change_type. (A real add_column typically lands here anyway,
        # since column-scoped lineage finds no *existing* consumer of a
        # column that didn't exist before the change -- ADDITIVE below is
        # reached only when the traversal does find references, e.g. a
        # widened type that existing consumers already read.)
        return MigrationDecision(
            decision_type=NO_MIGRATION_NEEDED,
            rationale=(
                f"No downstream asset references `{result.changed_column}` "
                f"({len(result.scanned)} scanned, 0 affected). No migration is needed."
            ),
        )

    if change_type in ADDITIVE_CHANGE_TYPES:
        return MigrationDecision(
            decision_type=ADDITIVE,
            rationale=(
                f"Declared change type '{change_type}' is non-breaking by construction (a new "
                "nullable column or a lossless type widening cannot invalidate an existing "
                f"consumer's query) -- {len(result.affected)} downstream asset(s) reference the "
                "changed column, but none require patching. Action: documentation proposal only; "
                "consumers notified, not patched."
            ),
        )

    return _decide_breaking(result)
