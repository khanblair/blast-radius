"""Output contract for the Assessment Engine -- consumed by Narrative (Phase 3),
Decision (Phase 4), and Dossier (Phase 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field

ORIGIN_HARD_BREAK = "ORIGIN_HARD_BREAK"
CASCADE_HARD_BREAK = "CASCADE_HARD_BREAK"
NOT_IMPACTED = "NOT_IMPACTED"

HARD_BREAK = "HARD_BREAK"
SILENT_CORRUPTION = "SILENT_CORRUPTION"
UNAFFECTED = "UNAFFECTED"


@dataclass
class AssetAssessment:
    urn: str
    name: str
    compile_status: str  # ORIGIN_HARD_BREAK | CASCADE_HARD_BREAK | NOT_IMPACTED
    select_star_exposure: bool
    evidence: list[str] = field(default_factory=list)
    hop: int | None = None
    usage_count: int = 0
    is_dashboard_exposed: bool = False
    owners: list[str] = field(default_factory=list)
    has_business_owner: bool = False
    severity_score: float = 0.0
    dbt_file_path: str | None = None  # project-relative, e.g. "models/staging/stg_customers.sql"; None when this asset has no local dbt model (e.g. a pure postgres-only sibling)

    @property
    def break_mode(self) -> str:
        if self.compile_status in (ORIGIN_HARD_BREAK, CASCADE_HARD_BREAK):
            return HARD_BREAK
        if self.select_star_exposure:
            return SILENT_CORRUPTION
        return UNAFFECTED


@dataclass
class AssessmentResult:
    changed_urn: str
    changed_column: str
    scanned: list[AssetAssessment] = field(default_factory=list)
    deepest_hop: int = 0
    mcp_call_trace: list[dict] = field(default_factory=list)

    @property
    def affected(self) -> list[AssetAssessment]:
        return [a for a in self.scanned if a.break_mode != UNAFFECTED]

    @property
    def hard_break_count(self) -> int:
        return sum(1 for a in self.scanned if a.break_mode == HARD_BREAK)

    @property
    def silent_corruption_count(self) -> int:
        return sum(1 for a in self.scanned if a.break_mode == SILENT_CORRUPTION)

    @property
    def unaffected_count(self) -> int:
        return sum(1 for a in self.scanned if a.break_mode == UNAFFECTED)
