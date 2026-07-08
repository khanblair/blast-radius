"""Loop 2 -- The Reasoning Loop: bounded, traced MCP tool-calling for Assessment.

Discipline (spec §4, Loop 2): no freeform ReAct wandering. Every call is one
of a small fixed set of read operations, capped by a tool-call budget and a
max lineage depth, and logged with a one-line rationale.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

TRACES_DIR = Path(__file__).resolve().parents[2] / "traces"


class ToolCallBudgetExceeded(RuntimeError):
    pass


@dataclass
class TraceEntry:
    call_number: int
    tool: str
    args: dict[str, Any]
    rationale: str
    result_summary: str


@dataclass
class ReasoningLoop:
    session: Any  # mcp.ClientSession
    run_id: str
    max_tool_calls: int = 30
    max_hops: int = 3
    trace: list[TraceEntry] = field(default_factory=list)

    async def _call(self, tool: str, args: dict[str, Any], rationale: str, summarize: Callable[[dict], str]) -> dict:
        if len(self.trace) >= self.max_tool_calls:
            raise ToolCallBudgetExceeded(f"Loop 2 tool-call budget ({self.max_tool_calls}) exhausted before calling {tool}")
        result = await self.session.call_tool(tool, arguments=args)
        text = result.content[0].text if result.content else "{}"
        data = json.loads(text)
        self.trace.append(
            TraceEntry(
                call_number=len(self.trace) + 1,
                tool=tool,
                args=args,
                rationale=rationale,
                result_summary=summarize(data),
            )
        )
        return data

    async def search(self, query: str, rationale: str) -> dict:
        return await self._call(
            "search", {"query": query, "num_results": 10}, rationale, lambda d: f"{d.get('total', 0)} matches"
        )

    async def get_lineage(self, urn: str, rationale: str, column: str | None = None, upstream: bool = False) -> dict:
        args: dict[str, Any] = {"urn": urn, "upstream": upstream, "max_hops": self.max_hops, "max_results": 100}
        if column:
            args["column"] = column
        direction_key = "upstreams" if upstream else "downstreams"
        return await self._call(
            "get_lineage", args, rationale, lambda d: f"{d.get(direction_key, {}).get('total', 0)} {direction_key}"
        )

    async def get_dataset_queries(self, urn: str, rationale: str, count: int = 1) -> dict:
        return await self._call(
            "get_dataset_queries", {"urn": urn, "count": count}, rationale, lambda d: f"{d.get('total', 0)} queries on record"
        )

    async def get_schema(self, urn: str, rationale: str, limit: int = 1000) -> dict:
        """Loop 5 (watch mode): fetch a dataset's current schema fields via
        the DataHub MCP server's `list_schema_fields` tool. `limit` is high
        by default since watch mode needs the *complete* column list to
        diff reliably -- a truncated fetch would look like spurious dropped
        columns."""
        return await self._call(
            "list_schema_fields", {"urn": urn, "limit": limit}, rationale, lambda d: f"{d.get('totalFields', 0)} fields"
        )

    def write_trace(self) -> Path:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACES_DIR / f"{self.run_id}.jsonl"
        with path.open("w") as f:
            for entry in self.trace:
                f.write(json.dumps(entry.__dict__) + "\n")
        return path
