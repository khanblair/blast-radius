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
from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.mcp_client import datahub_mcp_session


async def resolve_dataset_urn(loop: ReasoningLoop, table: str, platform: str) -> str:
    result = await loop.search(table, rationale=f"resolve `{table}` to a dataset URN")
    for r in result.get("searchResults", []):
        urn = r["entity"].get("urn", "")
        if urn.startswith("urn:li:dataset:") and f"urn:li:dataPlatform:{platform}" in urn:
            return urn
    raise SystemExit(f"Could not resolve a {platform} dataset URN for table '{table}'")


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
        changed_urn = await resolve_dataset_urn(resolver_loop, args.table, args.platform)

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
        with open(args.json_out, "w") as f:
            json.dump(
                {
                    "changed_urn": result.changed_urn,
                    "changed_column": result.changed_column,
                    "deepest_hop": result.deepest_hop,
                    "scanned": [asset.__dict__ for asset in result.scanned],
                },
                f,
                indent=2,
            )
        print(f"\nWrote assessment JSON to {args.json_out}")


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

    args = parser.parse_args(argv)
    if args.command == "assess":
        asyncio.run(_run_assess(args))


if __name__ == "__main__":
    main(sys.argv[1:])
