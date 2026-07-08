"""Watch Mode CLI (Phase 8, spec's Loop 5 -- the outer detection loop):
a single check-and-exit cycle.

    python -m agent.watch.cli --table raw_customers --schema public --platform postgres

Each run: resolves the table to a dataset URN and captures its current
schema via MCP (`schema_snapshot.capture_snapshot`), loads the previously
stored snapshot for this table from `--snapshot-dir` (if any), diffs them,
prints any `DetectedChange`s found, hands them to `run_watch_cycle` (using
the *real* pipeline_fn -- watch mode's whole point is autonomous triggering,
so this CLI never injects a fake), records what happened to the outcome
log, then saves the just-captured snapshot as the baseline for next time.

No `--interval`/daemon loop -- a single check-and-exit is sufficient for
this phase (run it again, e.g. from cron or a scheduler, for continuous
watch).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.mcp_client import datahub_mcp_session
from agent.watch.models import DetectedChange
from agent.watch.outcome import record_outcome
from agent.watch.schema_snapshot import capture_snapshot, diff_snapshots, load_snapshot, save_snapshot
from agent.watch.trigger import run_watch_cycle

DEFAULT_SNAPSHOT_DIR = Path("watch_state")


def _snapshot_path(snapshot_dir: Path, table: str) -> Path:
    return snapshot_dir / f"{table}.json"


def _default_outcome_log(snapshot_dir: Path) -> Path:
    return snapshot_dir / "outcomes.jsonl"


async def _run(args: argparse.Namespace) -> None:
    now = datetime.now(timezone.utc).isoformat()
    snapshot_path = _snapshot_path(args.snapshot_dir, args.table)

    previous = load_snapshot(snapshot_path)
    if previous is None:
        print(f"No baseline snapshot at {snapshot_path} -- this is a first run, capturing one now.")
    else:
        print(f"Loaded baseline snapshot from {snapshot_path} (captured_at={previous.captured_at}, {len(previous.columns)} columns).")

    async with datahub_mcp_session() as session:
        loop = ReasoningLoop(session=session, run_id=f"watch-{args.table}")
        current = await capture_snapshot(loop, args.table, args.schema, args.platform, captured_at=now)
    loop.write_trace()

    column_names = [c["name"] for c in current.columns]
    print(f"Captured current snapshot: {len(current.columns)} columns -- {column_names}")

    changes: list[DetectedChange] = [] if previous is None else diff_snapshots(previous, current)

    if not changes:
        print("No schema changes detected.")
    else:
        print(f"Detected {len(changes)} change(s):")
        for change in changes:
            print(f"  [{change.change_type}] {change.table}: {change.old_column} -> {change.new_column} -- {change.evidence}")

    triggered = run_watch_cycle(changes)
    triggered_results = {id(item["change"]): item["result"] for item in triggered}

    for change in changes:
        record_outcome(
            {
                "timestamp": now,
                "table": change.table,
                "change_type": change.change_type,
                "old_column": change.old_column,
                "new_column": change.new_column,
                "evidence": change.evidence,
                "pipeline_triggered": id(change) in triggered_results,
                "pipeline_result": triggered_results.get(id(change)),
            },
            args.outcome_log,
        )

    save_snapshot(current, snapshot_path)
    print(f"Saved current snapshot as new baseline at {snapshot_path}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blast-radius-watch")
    parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--platform", default="postgres")
    parser.add_argument("--snapshot-dir", dest="snapshot_dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--outcome-log", dest="outcome_log", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.outcome_log is None:
        args.outcome_log = _default_outcome_log(args.snapshot_dir)
    asyncio.run(_run(args))


if __name__ == "__main__":
    main(sys.argv[1:])
