"""Standalone narrative CLI (spec §3 Stage 2).

    python -m agent.narrative.cli --table raw_customers --column cust_id

Kept as its own entry point rather than extending
agent/orchestrator/cli.py's `assess` subcommand, so this work stays fully
isolated from a parallel Decision Engine change also touching that shared
file -- this module only *imports* from agent/orchestrator/cli.py
(`resolve_dataset_urn`, read-only) rather than modifying it.

Internally: resolve table -> URN via MCP search, run the Assessment Engine
(assess_change), then the Narrative Builder (build_narratives).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent.assessment.engine import assess_change
from agent.loops.reasoning_loop import ReasoningLoop
from agent.narrative.builder import build_narratives
from agent.narrative.models import NarrativeResult
from agent.orchestrator.cli import resolve_dataset_urn
from agent.orchestrator.mcp_client import datahub_mcp_session
from agent.paths import safe_output_path


def render_narratives(narrative_result: NarrativeResult) -> str:
    lines = [
        f"CAUSAL NARRATIVES -- {narrative_result.changed_urn} column `{narrative_result.changed_column}`",
        "",
    ]
    for n in narrative_result.narratives:
        lines.append(f"[{n.break_mode}] {n.name}  (source: {n.source})")
        lines.append(f"  {n.narrative_text}")
        lines.append("")
    if narrative_result.safe_summary:
        lines.append(narrative_result.safe_summary)
    return "\n".join(lines)


async def _run_narrate(args: argparse.Namespace) -> None:
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

    narrative_result = build_narratives(result, changed_table=args.table)

    print(render_narratives(narrative_result))
    if args.json_out:
        json_out_path = safe_output_path(args.json_out)
        json_text = json.dumps(
            {
                "changed_urn": narrative_result.changed_urn,
                "changed_column": narrative_result.changed_column,
                "safe_summary": narrative_result.safe_summary,
                "narratives": [n.__dict__ for n in narrative_result.narratives],
            },
            indent=2,
        )
        await asyncio.to_thread(json_out_path.write_text, json_text)
        print(f"\nWrote narrative JSON to {json_out_path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="blast-radius-narrate")
    parser.add_argument("--table", required=True, help="Bare table name, e.g. raw_customers")
    parser.add_argument("--column", required=True, help="Column being changed, e.g. cust_id")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--platform", default="postgres")
    parser.add_argument("--max-hops", dest="max_hops", type=int, default=3)
    parser.add_argument("--max-tool-calls", dest="max_tool_calls", type=int, default=30)
    parser.add_argument("--json-out", dest="json_out", default=None)

    args = parser.parse_args(argv)
    asyncio.run(_run_narrate(args))


if __name__ == "__main__":
    main(sys.argv[1:])
