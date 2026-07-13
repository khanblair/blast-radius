"""Declared-change CLI entry point (spec §3 Stage 0, declared mode).

    python -m agent.orchestrator.cli assess --table raw_customers --column cust_id

Resolves the table name to a URN via MCP `search` (rather than requiring the
caller to hand-construct one), then runs the Assessment Engine.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent.assessment.engine import assess_change
from agent.decision.engine import decide_migration
from agent.decision.gate import confirm_decision, render_decision
from agent.decision.models import AUTO_APPROVED
from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.mcp_client import datahub_mcp_session
from agent.paths import safe_output_path


async def resolve_dataset_urn(loop: ReasoningLoop, table: str, platform: str, schema: str | None = None) -> str:
    # Deliberately checks urn.startswith(...) rather than entity.get("type") --
    # `search` result entities carry no "type"/"name"/"platform" field at all
    # (only "properties" and "urn"), unlike `get_lineage` result entities,
    # which do. This is a real per-tool shape inconsistency in
    # mcp-server-datahub, not an oversight here -- see feedback-notes.md's
    # "Candidate upstream contributions" section for the drafted upstream
    # issue and live evidence. agent/assessment/engine.py's `entity.get("type")
    # == "DATASET"` checks are correct as written because they only ever
    # operate on get_lineage results, which do carry that field.
    result = await loop.search(table, rationale=f"resolve `{table}` to a dataset URN")
    # Trace this resolution even though the loop is otherwise discarded by
    # every current caller after this one search call -- without this, the
    # resolver's reasoning (and, now, which candidate schema matched) was
    # never written anywhere.
    loop.write_trace()

    platform_matches = [
        r["entity"].get("urn", "")
        for r in result.get("searchResults", [])
        if r["entity"].get("urn", "").startswith("urn:li:dataset:")
        and f"urn:li:dataPlatform:{platform}" in r["entity"].get("urn", "")
    ]

    if schema:
        # The URN's qualified name embeds the schema (e.g.
        # "warehouse.public.raw_customers") even though search result
        # entities carry no separate "schema" field -- so a same-named table
        # in a different schema can be told apart by matching that
        # substring, without needing a second MCP call. Only narrows the
        # candidate set when there's an actual schema-qualified match;
        # otherwise falls through to the unfiltered platform matches so this
        # stays backward compatible with URNs that don't embed a schema.
        schema_qualified = [urn for urn in platform_matches if f".{schema}.{table}," in urn]
        if schema_qualified:
            platform_matches = schema_qualified

    if platform_matches:
        return platform_matches[0]
    raise SystemExit(
        f"Could not resolve a {platform} dataset URN for table '{table}'"
        + (f" in schema '{schema}'" if schema else "")
    )


def render_summary(result) -> str:
    distinct_owners = {owner for asset in result.affected for owner in asset.owners}
    lines = [
        f"IMPACT ASSESSMENT -- {result.changed_urn} column `{result.changed_column}`",
        f"  {len(result.scanned)} scanned / {len(result.affected)} affected"
        f" -- {result.hard_break_count} hard breaks, {result.silent_corruption_count} silent risks,"
        f" {result.unaffected_count} confirmed safe -- {len(distinct_owners)} owners -- deepest hop {result.deepest_hop}",
        "",
        "SEVERITY MATRIX (ranked):",
    ]
    for asset in result.scanned:
        lines.append(
            f"  [{asset.severity_score:6.1f}] {asset.name:<20} {asset.break_mode:<18}"
            f" hop={asset.hop} usage={asset.usage_count} dashboard_exposed={asset.is_dashboard_exposed}"
        )
        for e in asset.evidence:
            lines.append(f"           evidence: {e}")
    return "\n".join(lines)


async def _run_assess(args: argparse.Namespace) -> None:
    async with datahub_mcp_session() as session:
        resolver_loop = ReasoningLoop(session=session, run_id="resolve")
        changed_urn = await resolve_dataset_urn(resolver_loop, args.table, args.platform, schema=args.schema)

    result = await assess_change(
        changed_urn=changed_urn,
        changed_column=args.column,
        source_schema=args.schema,
        source_table=args.table,
        max_hops=args.max_hops,
        max_tool_calls=args.max_tool_calls,
    )

    print(render_summary(result))
    if args.json_out:
        json_out_path = safe_output_path(args.json_out)
        json_text = json.dumps(
            {
                "changed_urn": result.changed_urn,
                "changed_column": result.changed_column,
                "deepest_hop": result.deepest_hop,
                "scanned": [asset.__dict__ for asset in result.scanned],
            },
            indent=2,
        )
        await asyncio.to_thread(json_out_path.write_text, json_text)
        print(f"\nWrote assessment JSON to {json_out_path}")


async def _run_decide(args: argparse.Namespace) -> None:
    """Stage 3 / Loop 4 gate #1: run the same assessment `assess` runs, feed
    it through the deterministic Decision Engine, render the result, and
    apply the human confirmation gate (skipped non-interactively when
    `--auto-approve` is passed)."""
    async with datahub_mcp_session() as session:
        resolver_loop = ReasoningLoop(session=session, run_id="resolve")
        changed_urn = await resolve_dataset_urn(resolver_loop, args.table, args.platform, schema=args.schema)

    result = await assess_change(
        changed_urn=changed_urn,
        changed_column=args.column,
        source_schema=args.schema,
        source_table=args.table,
        max_hops=args.max_hops,
        max_tool_calls=args.max_tool_calls,
    )

    decision = decide_migration(result, change_type=args.change_type)

    print(render_summary(result))
    print()
    print(render_decision(decision))

    confirm_decision(decision, auto_approve=args.auto_approve)

    print()
    if decision.recommended_strategy is None:
        print(f"CONFIRMATION: not applicable ({decision.decision_type})")
    elif decision.confirmation_mode == AUTO_APPROVED:
        print(f"CONFIRMATION: auto-approved -- proceeding with Strategy {decision.confirmed_strategy}")
    else:
        print(f"CONFIRMATION: human-confirmed -- proceeding with Strategy {decision.confirmed_strategy}")


def _add_decide_parser(subparsers: argparse._SubParsersAction) -> None:
    decide_parser = subparsers.add_parser(
        "decide", help="Decide whether a declared column change needs a migration, and which strategy"
    )
    decide_parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    decide_parser.add_argument("--column", required=True, help="Column being changed, e.g. cust_id")
    decide_parser.add_argument("--schema", default="public")
    decide_parser.add_argument("--platform", default="postgres")
    decide_parser.add_argument("--max-hops", dest="max_hops", type=int, default=3)
    decide_parser.add_argument("--max-tool-calls", dest="max_tool_calls", type=int, default=30)
    decide_parser.add_argument(
        "--change-type",
        dest="change_type",
        default="rename",
        choices=["rename", "add_column", "widen_type", "drop_column"],
        help="Nature of the declared change -- determines ADDITIVE eligibility",
    )
    decide_parser.add_argument(
        "--auto-approve",
        dest="auto_approve",
        action="store_true",
        help="Skip the interactive confirmation prompt (required for scripted/non-interactive runs)",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="blast-radius")
    subparsers = parser.add_subparsers(dest="command", required=True)

    assess_parser = subparsers.add_parser("assess", help="Assess the blast radius of a declared column change")
    assess_parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    assess_parser.add_argument("--column", required=True, help="Column being changed, e.g. cust_id")
    assess_parser.add_argument("--schema", default="public")
    assess_parser.add_argument("--platform", default="postgres")
    assess_parser.add_argument("--max-hops", dest="max_hops", type=int, default=3)
    assess_parser.add_argument("--max-tool-calls", dest="max_tool_calls", type=int, default=30)
    assess_parser.add_argument("--json-out", dest="json_out", default=None)

    _add_decide_parser(subparsers)

    args = parser.parse_args(argv)
    if args.command == "assess":
        asyncio.run(_run_assess(args))
    elif args.command == "decide":
        asyncio.run(_run_decide(args))


if __name__ == "__main__":
    main(sys.argv[1:])
