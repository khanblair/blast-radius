# agent/verify/models.py
"""Output contract for the Verification Harness (spec Stage 5 / Loop 3) --
consumed by Loop 1 (Codegen self-correction, Phase 5, built in parallel)."""
from __future__ import annotations
from dataclasses import dataclass, field

V1_STATIC = "V1_STATIC"
V2_COMPILE = "V2_COMPILE"


@dataclass
class VerificationOutcome:
    level: str          # V1_STATIC | V2_COMPILE
    passed: bool
    message: str        # human-readable one-liner
    raw_error: str | None = None   # exact error text -- this is what Loop 1 injects into its next generation attempt as failure evidence, so it MUST be substantive and specific, never empty or vague, on any failure


@dataclass
class VerificationReport:
    artifact_path: str  # e.g. "models/staging/stg_customers.sql", project-relative
    outcomes: list[VerificationOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

    @property
    def first_failure(self) -> VerificationOutcome | None:
        return next((o for o in self.outcomes if not o.passed), None)
