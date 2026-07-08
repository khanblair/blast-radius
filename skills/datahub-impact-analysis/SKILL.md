---
name: datahub-impact-analysis
description: Use when a schema change is proposed or detected on a DataHub-tracked table/column and you need to know what actually breaks downstream, how badly, and who owns it -- via the DataHub MCP Server's read tools (search, get_lineage, get_dataset_queries).
---

# DataHub Impact Analysis

Extracted from [Blast Radius](../../README.md)'s Assessment Engine (`agent/assessment/`), built for "Build with DataHub: The Agent Hackathon." This skill packages the *general* technique — independent of Blast Radius's own dbt/Postgres demo estate — for any agent that has DataHub MCP tool access and needs to answer: **"if this column changes, what actually breaks, how loudly, and does anyone with a business stake notice?"**

## When to use this

- A human declares an intended change ("I'm renaming `orders.cust_id`") before making it, and wants a go/no-go read.
- A watcher detects a schema diff has *already* happened and needs to triage the blast radius before anyone notices the hard way.
- Any case where "grep the codebase for the column name" would be too shallow (misses structural cascades, can't rank by real usage, can't see ownership).

## The core technique

### 1. Resolve the changed entity to a URN — don't hand-construct it

Use the `search` tool, not string formatting. URN construction is fragile (platform, environment casing, and struct shape vary), and `search` is exact for this: match on the bare table name, then filter results to the URN whose platform and type match what you expect.

```python
result = await session.call_tool("search", {"query": table_name, "num_results": 10})
urn = next(
    r["entity"]["urn"] for r in result["searchResults"]
    if r["entity"]["urn"].startswith("urn:li:dataset:") and f"dataPlatform:{platform}" in r["entity"]["urn"]
)
```

**Gotcha:** different DataHub MCP tools shape their result entities differently. `search` results often have no `"type"` field on the entity at all, while `get_lineage` results do — don't assume a uniform entity shape across tools; check what's actually there for the specific tool you're calling before writing a filter condition. (This exact assumption mismatch shipped a bug in Blast Radius's first draft — see `feedback-notes.md`.)

### 2. Run TWO lineage queries, not one — column-scoped and broad

A single dataset-level lineage call answers "what's downstream of this table," but not "what's downstream of *this specific column*." You need both, for different purposes:

```python
column_scoped = await session.call_tool("get_lineage", {
    "urn": urn, "upstream": False, "column": changed_column, "max_hops": 3, "max_results": 100,
})
broad = await session.call_tool("get_lineage", {
    "urn": urn, "upstream": False, "max_hops": 3, "max_results": 100,
})
```

- **Column-scoped** membership tells you which downstream assets *structurally depend on this specific column* — this is your hard-break candidate set.
- **Broad** (dataset-level) reachability is wider — use it for "confirmed safe" reporting (an asset reachable from the changed table but *not* in column scope is a real, checked "safe," not just "we didn't look") and for locating a downstream dashboard entity to test exposure against (step 5).

### 3. Classify breaks structurally, never by scanning text for the column name

The column name alone isn't enough: a descendant model can re-select a same-named column it inherited from an *ancestor*, without being the origin of the break (e.g. a `dim_customers` model re-selecting `cust_id` it got from `stg_customers`, not from the raw table). Distinguish:

- **Origin break** — this asset's own query directly reads the *physical, changed table* (check the FROM/JOIN clauses of its actual compiled/rendered SQL, via a real SQL parser like `sqlglot` against table+schema identity — not a text search for the column name anywhere in the file).
- **Cascade break** — this asset is in column scope (so something downstream of it will break) but its own query doesn't read the changed table directly; it only fails because an upstream dependency does.

This distinction matters because the fix differs: you patch the *origin*, and cascades often need zero changes once the origin's output shape is restored.

### 4. Check for `SELECT *` exposure as an independent, structural signal

An asset that expands an upstream table via unpinned `SELECT *` (or `alias.*`) is a standing fragility risk *regardless of whether the current declared change happens to hit it* — treat this as its own boolean flag on the asset, computed from the asset's own SQL structure, not derived from whether today's specific change breaks it. This is what lets you say "nothing breaks today, but this asset will silently inherit whatever changes next" — a genuinely different, valuable finding from "safe."

### 5. Weight severity by real usage, exposure, and ownership — not just graph distance

Hop count alone is a poor severity proxy (a hop-1 asset nobody queries matters less than a hop-3 asset behind a live dashboard). Pull what DataHub actually knows:

```python
usage = await session.call_tool("get_dataset_queries", {"urn": asset_urn, "count": 1})
# usage["total"] -- recorded query volume against this specific asset
```

Find dashboard exposure by running lineage *upstream* from any dashboard entity found in your broad downstream results, and checking whether your scanned asset is in that upstream set — cheaper than checking every asset individually:

```python
dashboard_upstream = await session.call_tool("get_lineage", {"urn": dashboard_urn, "upstream": True, "max_hops": 3})
```

Ownership comes off the entity's own `ownership.owners` — distinguish a `BUSINESS_OWNER` from a `TECHNICAL_OWNER`; a business owner on the hook changes who needs to be looped in, not just whether the pipeline breaks.

## Known platform quirks worth budgeting for

- **Postgres + dbt ingestion do not sibling-merge into one URN by default**, even with matching `env`/`platform_instance` config. You get two parallel entities per physical table (`dataPlatform:postgres,...` and `dataPlatform:dbt,...`), bridged by an `upstreamLineage` edge — not a `Siblings` aspect. If you need data that's only emitted to one platform's entity (e.g. a dbt-specific custom property like a file path) while other enrichment (ownership, usage) lives on the other, track both entities per logical table rather than collapsing to whichever one you find first.
- **Budget your lineage hop depth to account for platform-bridge hops.** A raw table → staging → mart chain may traverse more graph hops than its "conceptual" depth suggests, because of the postgres/dbt platform-alternation above.
- **Always cap your tool-call budget and log a one-line rationale per call.** Unbounded agentic lineage-walking on a real (non-demo) DataHub instance can fan out arbitrarily; a fixed budget plus a trace of every call (tool, args, rationale, one-line result summary) makes the whole assessment auditable and keeps it from ever running away.

## Reference implementation

The full, tested implementation of this pattern lives in this repo:
- `agent/loops/reasoning_loop.py` — the budgeted, traced MCP-calling wrapper (`ReasoningLoop`).
- `agent/assessment/break_mode.py` — the sqlglot-based structural origin/cascade + `SELECT *` classification.
- `agent/assessment/severity.py` — the usage × exposure × ownership severity weighting.
- `agent/assessment/engine.py` — `assess_change()`, wiring all of the above together end to end.

`feedback-notes.md` at the repo root has the full, dated log of friction encountered building this against a real DataHub Core + MCP Server instance — useful context for anyone else building on top of the same MCP tools.
