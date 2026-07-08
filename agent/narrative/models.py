"""Output contract for the Narrative Builder (spec §3 Stage 2) -- consumed by
Decision (Phase 4) and Dossier (Phase 7).

Mirrors the separation-of-concerns style of agent/assessment/models.py: a
plain dataclass contract with no behavior beyond shaping the data that
agent/narrative/builder.py produces.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AssetNarrative:
    urn: str
    name: str
    narrative_text: str
    evidence_cited: list[str] = field(default_factory=list)
    break_mode: str = ""
    source: str = "template"  # "llm" | "template" -- which path produced narrative_text


@dataclass
class NarrativeResult:
    changed_urn: str
    changed_column: str
    narratives: list[AssetNarrative] = field(default_factory=list)
    safe_summary: str | None = None  # one-line note on UNAFFECTED assets, if any
