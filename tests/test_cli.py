import asyncio
import json

import pytest

from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, AssessmentResult, AssetAssessment
from agent.assessment.severity import rank
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


def test_resolve_dataset_urn_picks_matching_platform_without_a_type_field():
    # The real `search` tool's entity payloads have no "type" field (unlike
    # get_lineage's) -- resolution must not depend on one.
    results = [
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.public.raw_customers,PROD)", "properties": {"name": "raw_customers"}}},
        {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)", "properties": {"name": "warehouse.public.raw_customers"}}},
    ]
    loop = ReasoningLoop(session=FakeSession(results), run_id="test")
    urn = run(resolve_dataset_urn(loop, "raw_customers", "postgres"))
    assert urn == "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)"


def test_resolve_dataset_urn_raises_when_no_match():
    loop = ReasoningLoop(session=FakeSession([]), run_id="test")
    with pytest.raises(SystemExit):
        run(resolve_dataset_urn(loop, "nonexistent", "postgres"))


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
