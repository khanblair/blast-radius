"""Data models for Watch Mode (Loop 5): schema snapshots and detected changes.

`SchemaSnapshot.columns` shape is our choice, derived from what the DataHub
MCP server's `list_schema_fields` tool actually returns (see
`ReasoningLoop.get_schema` and `schema_snapshot.capture_snapshot`): each raw
field is a dict with (among other things) `fieldPath` and `nativeDataType`
keys. We narrow that down to exactly what the diff logic needs:

    {"name": <fieldPath>, "type": <nativeDataType>}

e.g. ``{"name": "cust_id", "type": "varchar"}``. Only `name` currently drives
detection (`diff_snapshots` compares column names, not types) -- `type` is
carried along for completeness / future use, not because current detection
logic reads it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SchemaSnapshot:
    table: str
    columns: list[dict]  # [{"name": "cust_id", "type": "varchar"}, ...]
    captured_at: str  # ISO timestamp string, supplied by the caller


@dataclass
class DetectedChange:
    table: str
    change_type: str  # "possible_rename" | "add_column" | "drop_column"
    old_column: str | None
    new_column: str | None
    evidence: str  # human-readable note explaining the classification
