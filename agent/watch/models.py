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
    schema: str  # e.g. "public" -- carried so a same-named table in a
    # different schema/platform gets its own snapshot file and never gets
    # diffed against, or triggers a pipeline run for, the wrong table (see
    # agent/watch/cli.py's _snapshot_path and agent/watch/trigger.py).
    platform: str  # e.g. "postgres"
    columns: list[dict]  # [{"name": "cust_id", "type": "varchar"}, ...]
    captured_at: str  # ISO timestamp string, supplied by the caller


@dataclass
class DetectedChange:
    table: str
    schema: str  # threaded through so run_watch_cycle can hand the *correct*
    # schema/platform to the pipeline instead of letting it silently fall
    # back to run_full_pipeline's schema="public"/platform="postgres"
    # defaults for a change detected on a different one.
    platform: str
    change_type: str  # "possible_rename" | "add_column" | "drop_column"
    old_column: str | None
    new_column: str | None
    evidence: str  # human-readable note explaining the classification
