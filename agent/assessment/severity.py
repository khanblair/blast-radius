"""Severity scoring: break_mode weight x usage x exposure x ownership criticality.

Per spec §3 Stage 1: "break_mode weight x usage frequency (DataHub query
history) x exposure (dashboard-facing vs internal) x ownership criticality
(domain/tier tags)". Ownership criticality uses ownership *type* already in
the estate (BUSINESS_OWNER on marts, TECHNICAL_OWNER on raw/staging) rather
than a separate tier-tagging pass -- a real signal already present, not a
constant stand-in.
"""
from __future__ import annotations

from agent.assessment.models import HARD_BREAK, SILENT_CORRUPTION, UNAFFECTED, AssetAssessment

BREAK_MODE_WEIGHT = {
    HARD_BREAK: 10.0,
    SILENT_CORRUPTION: 6.0,
    UNAFFECTED: 0.0,
}

DASHBOARD_EXPOSURE_MULTIPLIER = 2.0
NO_EXPOSURE_MULTIPLIER = 1.0

BUSINESS_OWNER_WEIGHT = 2.0
TECHNICAL_OWNER_WEIGHT = 1.0


def score(asset: AssetAssessment) -> float:
    break_weight = BREAK_MODE_WEIGHT[asset.break_mode]
    usage_factor = 1.0 + (asset.usage_count / 10.0)
    exposure_factor = DASHBOARD_EXPOSURE_MULTIPLIER if asset.is_dashboard_exposed else NO_EXPOSURE_MULTIPLIER
    ownership_factor = BUSINESS_OWNER_WEIGHT if asset.has_business_owner else TECHNICAL_OWNER_WEIGHT
    return round(break_weight * usage_factor * exposure_factor * ownership_factor, 2)


def rank(assets: list[AssetAssessment]) -> list[AssetAssessment]:
    """Assigns severity_score to each asset in place and returns them sorted
    descending -- the ranked severity matrix (spec §5, item 2)."""
    for asset in assets:
        asset.severity_score = score(asset)
    return sorted(assets, key=lambda a: a.severity_score, reverse=True)
