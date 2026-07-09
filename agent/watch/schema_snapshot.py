"""Loop 5 (Watch Mode) -- schema snapshotting: capture a table's live column
list via MCP, persist it to disk, and diff two snapshots to detect drift.

`diff_snapshots` is the core detection heuristic and is deliberately dumb,
per spec: a schema diff alone cannot distinguish a real column rename from
an unrelated drop+add that happened to land in the same watch interval. So:

  - exactly one column disappeared and exactly one appeared -> reported as a
    single `possible_rename` DetectedChange, with the ambiguity spelled out
    in `evidence` (it's a guess, not a certainty).
  - any other combination (0, 2+, or mismatched counts) -> each disappearance
    and each appearance is reported as an independent `drop_column` /
    `add_column` DetectedChange. No pairing is attempted -- guessing wrong
    pairings would be worse than not guessing at all.
  - nothing changed -> empty list.

This function does no I/O and can be exhaustively tested with fabricated
`SchemaSnapshot` objects.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.cli import resolve_dataset_urn
from agent.watch.models import DetectedChange, SchemaSnapshot


async def capture_snapshot(loop: ReasoningLoop, table: str, schema: str, platform: str, captured_at: str) -> SchemaSnapshot:
    """Resolves `table` to a dataset URN (the same `search`-based resolution
    declared mode's CLI uses, see `agent.orchestrator.cli.resolve_dataset_urn`)
    and fetches its current schema fields via `ReasoningLoop.get_schema`,
    which wraps the DataHub MCP server's `list_schema_fields` tool.

    `schema` is passed through to `resolve_dataset_urn`, which uses it to
    disambiguate same-named tables in different schemas (matched against the
    resolved URN's qualified name) -- without it, a table name that exists
    in more than one schema on this platform would resolve non-
    deterministically to whichever match `search` happened to rank first.
    """
    urn = await resolve_dataset_urn(loop, table, platform, schema=schema)
    result = await loop.get_schema(urn, rationale=f"capture current schema snapshot for `{table}`")
    columns = [
        {"name": field.get("fieldPath"), "type": field.get("nativeDataType")}
        for field in result.get("fields", [])
    ]
    return SchemaSnapshot(table=table, schema=schema, platform=platform, columns=columns, captured_at=captured_at)


def save_snapshot(snapshot: SchemaSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), indent=2))


def load_snapshot(path: Path) -> SchemaSnapshot | None:
    """Returns None both when there's no file yet AND when the file exists
    but can't be loaded as a valid SchemaSnapshot (corrupted JSON, or an
    older/incompatible format missing a field this version requires) --
    either way there's no usable baseline, so this degrades to "first run"
    behavior instead of crashing the whole watch cycle over one bad file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return SchemaSnapshot(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def diff_snapshots(old: SchemaSnapshot, new: SchemaSnapshot) -> list[DetectedChange]:
    old_names = {c["name"] for c in old.columns}
    new_names = {c["name"] for c in new.columns}

    disappeared = sorted(old_names - new_names)
    appeared = sorted(new_names - old_names)

    if not disappeared and not appeared:
        return []

    if len(disappeared) == 1 and len(appeared) == 1:
        old_col, new_col = disappeared[0], appeared[0]
        return [
            DetectedChange(
                table=new.table,
                schema=new.schema,
                platform=new.platform,
                change_type="possible_rename",
                old_column=old_col,
                new_column=new_col,
                evidence=(
                    f"Column `{old_col}` disappeared and `{new_col}` appeared between snapshots -- "
                    "heuristic guess only: a real rename and an unrelated drop+add are "
                    "indistinguishable from a schema diff alone."
                ),
            )
        ]

    changes: list[DetectedChange] = []
    for col in disappeared:
        changes.append(
            DetectedChange(
                table=new.table,
                schema=new.schema,
                platform=new.platform,
                change_type="drop_column",
                old_column=col,
                new_column=None,
                evidence=f"Column `{col}` was present in the previous snapshot and is absent from the current one.",
            )
        )
    for col in appeared:
        changes.append(
            DetectedChange(
                table=new.table,
                schema=new.schema,
                platform=new.platform,
                change_type="add_column",
                old_column=None,
                new_column=col,
                evidence=f"Column `{col}` is present in the current snapshot and was absent from the previous one.",
            )
        )
    return changes
