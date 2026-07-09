"""Output contract for the Migration Decision Engine (Phase 4, spec §3 Stage 3
and §4 Loop 4 gate #1) -- consumed by the CLI confirmation gate and, later,
the Dossier renderer's "4. Migration Decision" section (spec §5).
"""
from __future__ import annotations

from dataclasses import dataclass, field

NO_MIGRATION_NEEDED = "NO_MIGRATION_NEEDED"
ADDITIVE = "ADDITIVE"
BREAKING = "BREAKING"

# `decision_type` is a bare str, not a closed Enum -- callers that branch on
# it (agent/dossier/renderer.py in particular) should check membership in
# this set rather than assuming "not BREAKING" means one of the two known
# non-breaking types, so an unrecognized future value can't silently fall
# through to the wrong branch.
KNOWN_DECISION_TYPES = frozenset({NO_MIGRATION_NEEDED, ADDITIVE, BREAKING})

# Loop 4 gate #1 confirmation provenance. *How* a decision was confirmed
# matters as much as *whether* it was -- a tool whose selling point is trust
# must never claim a human signed off on something nobody was actually asked
# about. AUTO_APPROVED exists purely so the pipeline is scriptable (demo,
# watch-mode policy default, tests that must never block on stdin);
# NOT_APPLICABLE covers decisions with no strategy to confirm at all.
HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
AUTO_APPROVED = "AUTO_APPROVED"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class StrategyOption:
    """One of the 2-3 named strategies offered for a BREAKING decision."""

    strategy_id: str  # "A" | "B" | "C"
    name: str
    description: str
    tradeoffs: str


@dataclass
class RejectedStrategy:
    """A strategy that was considered and explicitly not recommended, with
    the reason -- so the dossier can print "rejected: A, C (reasons)"
    (spec §5) instead of silently dropping the alternatives."""

    strategy_id: str
    reason: str


@dataclass
class MigrationDecision:
    decision_type: str  # NO_MIGRATION_NEEDED | ADDITIVE | BREAKING
    rationale: str
    options: list[StrategyOption] = field(default_factory=list)
    recommended_strategy: str | None = None  # strategy_id, or None when there's nothing to choose between
    rejected: list[RejectedStrategy] = field(default_factory=list)
    human_confirmed: bool = False
    confirmed_strategy: str | None = None
    confirmation_mode: str = NOT_APPLICABLE  # HUMAN_CONFIRMED | AUTO_APPROVED | NOT_APPLICABLE
