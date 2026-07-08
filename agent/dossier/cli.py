"""Standalone dossier CLI (Phase 7) -- the demo's actual spine: runs the
full spec pipeline end to end (agent.dossier.pipeline.run_full_pipeline) and
prints the resulting dossier, plus a PR preview/result.

    python -m agent.dossier.cli --table raw_customers --old-column cust_id --new-column customer_id [--auto-approve] [--create-pr]

SAFETY: `--create-pr` sets create_pr_live=True, which would attempt a REAL
GitHub PR via PyGithub against the real khanblair/blast-radius repo. Per
this project's absolute safety rules for Phase 7, this flag must never
actually be passed during development, testing, or live-verification of
this tool -- GITHUB_TOKEN is blank in .env (so it would fail anyway), but
more importantly this repo's live git working copy and the real `khanblair`
GitHub identity must never be touched by an automated run. Every live
verification of this CLI uses only the default dry-run path.
"""
from __future__ import annotations

import argparse
import sys

from agent.dossier.pipeline import run_full_pipeline


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
        max_hops=args.max_hops,
        max_tool_calls=args.max_tool_calls,
        max_attempts=args.max_attempts,
    )

    print(result["dossier_markdown"])

    if not result["pr_attempted"]:
        print()
        print("No code change was needed -- PR delivery skipped.")
    elif result["pr_result"] is not None:
        print()
        print(f"PR created: {result['pr_result']}")
    # else: create_pr already printed its dry-run preview as a side effect.


if __name__ == "__main__":
    main(sys.argv[1:])
