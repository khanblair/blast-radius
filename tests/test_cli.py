import asyncio
import json

import pytest

from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, AssessmentResult, AssetAssessment
from agent.assessment.severity import rank
from agent.loops import reasoning_loop as rl
from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.cli import render_summary, resolve_dataset_urn


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, data):
        self.content = [FakeContent(json.dumps(data))]


class FakeSession:
    def __init__(self, search_results):
        self._search_results = search_results

    async def call_tool(self, name, arguments):
        return FakeResult({"total": len(self._search_results), "searchResults": self._search_results})


def run(coro):
    return asyncio.run(coro)


def test_resolve_dataset_urn_picks_matching_platform_without_a_type_field(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    # The real `search` tool's entity payloads have no "type" field (unlike
    # get_lineage's) -- resolution must not depend on one.
    results = [
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.public.raw_customers,PROD)", "properties": {"name": "raw_customers"}}},
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)", "properties": {"name": "warehouse.public.raw_customers"}}},
    ]
    loop = ReasoningLoop(session=FakeSession(results), run_id="test")
    urn = run(resolve_dataset_urn(loop, "raw_customers", "postgres"))
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)"


def test_resolve_dataset_urn_raises_when_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    loop = ReasoningLoop(session=FakeSession([]), run_id="test")
    with pytest.raises(SystemExit):
        run(resolve_dataset_urn(loop, "nonexistent", "postgres"))


def test_resolve_dataset_urn_writes_a_trace(tmp_path, monkeypatch):
    # Regression coverage for a confirmed bug: every current caller builds a
    # dedicated resolver ReasoningLoop, uses it for exactly this one search
    # call, then discards it -- write_trace() was never called on it, so the
    # resolution reasoning was silently lost. resolve_dataset_urn must write
    # its own trace before returning.
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    results = [
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)", "properties": {"name": "warehouse.public.raw_customers"}}},
    ]
    loop = ReasoningLoop(session=FakeSession(results), run_id="test-resolve-trace")
    run(resolve_dataset_urn(loop, "raw_customers", "postgres"))

    trace_path = tmp_path / "test-resolve-trace.jsonl"
    assert trace_path.exists()
    assert trace_path.read_text().strip()  # non-empty: at least the search call was recorded


def test_resolve_dataset_urn_disambiguates_same_named_table_in_different_schema(tmp_path, monkeypatch):
    # Regression coverage for a confirmed bug: resolution only ever filtered
    # by platform, so two same-named tables in different schemas resolved
    # non-deterministically to whichever `search` happened to rank first.
    # The URN's qualified name embeds the schema even though search result
    # entities carry no separate "schema" field, so that's what must be
    # matched against.
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    results = [
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.sales.orders,PROD)", "properties": {"name": "orders"}}},
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.archive.orders,PROD)", "properties": {"name": "orders"}}},
    ]
    loop = ReasoningLoop(session=FakeSession(results), run_id="test")
    urn = run(resolve_dataset_urn(loop, "orders", "postgres", schema="archive"))
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.archive.orders,PROD)"


def test_resolve_dataset_urn_schema_filter_falls_back_when_no_schema_qualified_match(tmp_path, monkeypatch):
    # A schema that doesn't match any candidate URN must not turn a
    # resolvable table into an unresolvable one -- fall back to the
    # unfiltered platform matches rather than raising, since not every real
    # URN necessarily embeds a schema-qualified name.
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    results = [
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)", "properties": {"name": "raw_customers"}}},
    ]
    loop = ReasoningLoop(session=FakeSession(results), run_id="test")
    urn = run(resolve_dataset_urn(loop, "raw_customers", "postgres", schema="some_other_schema"))
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)"


def test_render_summary_counts_distinct_owners_and_break_modes():
    hard = AssetAssessment(
        urn="urn:1", name="stg_customers", compile_status=CASCADE_HARD_BREAK, select_star_exposure=False,
        owners=["urn:li:corpuser:jchen"],
    )
    safe = AssetAssessment(
        urn="urn:2", name="fct_orders", compile_status=NOT_IMPACTED, select_star_exposure=False,
        owners=["urn:li:corpuser:asmith"],
    )
    rank([hard, safe])
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[hard, safe], deepest_hop=2)

    output = render_summary(result)
    assert "2 scanned / 1 affected" in output
    assert "1 hard breaks" in output
    assert "1 confirmed safe" in output
    assert "1 owners" in output  # only the affected asset's owner counts
    assert "deepest hop 2" in output
