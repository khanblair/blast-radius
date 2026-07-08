"""Standalone dossier CLI (Phase 7) -- the demo's actual spine: runs the
full spec pipeline end to end (agent.dossier.pipeline.run_full_pipeline),
prints the resulting dossier, and saves it to disk under dossiers/ (or
--output) so there's a durable file to open/share after the run, not just
terminal scrollback.

    python -m agent.dossier.cli --table raw_customers --old-column cust_id --new-column customer_id [--auto-approve] [--create-pr] [--write-to-datahub] [--output PATH]

SAFETY: `--create-pr` sets create_pr_live=True, which would attempt a REAL
GitHub PR via PyGithub against the real khanblair/blast-radius repo. Per
this project's absolute safety rules for Phase 7, this flag must never
actually be passed during development, testing, or live-verification of
this tool -- GITHUB_TOKEN is blank in .env (so it would fail anyway), but
more importantly this repo's live git working copy and the real `khanblair`
GitHub identity must never be touched by an automated run. Every live
verification of this CLI uses only the default dry-run path.

`--write-to-datahub` is a different, much lower-risk category of action --
it writes a Document entity into THIS PROJECT'S OWN local DataHub instance
(the metadata platform, not any git/GitHub repo), visible from the affected
datasets' own pages in the DataHub UI. Off by default, matching the
`save_document` MCP tool's own "confirm with the user before saving"
guidance -- safe to pass freely against a local dev instance, unlike
`--create-pr`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.dossier.pipeline import run_full_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
DOSSIERS_DIR = REPO_ROOT / "dossiers"


def _default_output_path(table: str, old_column: str, new_column: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{table}-{old_column}-to-{new_column}-{timestamp}.md"
    return DOSSIERS_DIR / filename


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="blast-radius-dossier")
    parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    parser.add_argument("--old-column", required=True, dest="old_column", help="Column being renamed away from, e.g. cust_id")
    parser.add_argument("--new-column", required=True, dest="new_column", help="Column being renamed to, e.g. customer_id")
    parser.add_argument(
        "--change-type",
        dest="change_type",
        default="rename",
        choices=["rename", "add_column", "widen_type", "drop_column"],
        help="Nature of the declared change -- determines ADDITIVE eligibility",
    )
    parser.add_argument("--schema", default="public")
    parser.add_argument("--platform", default="postgres")
    parser.add_argument(
        "--auto-approve",
        dest="auto_approve",
        action="store_true",
        help="Skip the interactive migration-decision confirmation prompt (Loop 4 gate #1)",
    )
    parser.add_argument(
        "--create-pr",
        dest="create_pr",
        action="store_true",
        help=(
            "DANGEROUS: opens a real GitHub PR via PyGithub instead of printing a dry-run "
            "preview. Never pass this during development/testing -- see this module's docstring."
        ),
    )
    parser.add_argument(
        "--write-to-datahub",
        dest="write_to_datahub",
        action="store_true",
        help=(
            "Persist the rendered dossier as a Document in this project's own local DataHub "
            "instance, linked to every affected asset. Off by default -- see this module's docstring."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output",
        default=None,
        help="Path to save the dossier markdown to. Defaults to dossiers/<table>-<old>-to-<new>-<timestamp>.md",
    )
    parser.add_argument("--max-hops", dest="max_hops", type=int, default=3)
    parser.add_argument("--max-tool-calls", dest="max_tool_calls", type=int, default=30)
    parser.add_argument("--max-attempts", dest="max_attempts", type=int, default=3)

    args = parser.parse_args(argv)

    result = run_full_pipeline(
        args.table,
        args.old_column,
        args.new_column,
        change_type=args.change_type,
        schema=args.schema,
        platform=args.platform,
        auto_approve_decision=args.auto_approve,
        create_pr_live=args.create_pr,
        write_to_datahub=args.write_to_datahub,
        max_hops=args.max_hops,
        max_tool_calls=args.max_tool_calls,
        max_attempts=args.max_attempts,
    )

    if result["pr_attempted"] and result["pr_result"] is None:
        # Dry-run: create_pr already printed a full preview (dossier
        # included as the would-be PR body) as a side effect -- printing
        # the dossier again here would just duplicate it.
        pass
    else:
        print(result["dossier_markdown"])
        if not result["pr_attempted"]:
            print()
            print("No code change was needed -- PR delivery skipped.")
        else:
            print()
            print(f"PR created: {result['pr_result']}")

    if result["datahub_write_attempted"]:
        print()
        if result["datahub_document_urn"]:
            print(f"Dossier saved to DataHub: {result['datahub_document_urn']}")
        else:
            print("Dossier write to DataHub was attempted but did not succeed (see traces/ for details).")

    output_path = Path(args.output) if args.output else _default_output_path(args.table, args.old_column, args.new_column)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result["dossier_markdown"])
    print()
    print(f"Dossier saved to: {output_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
