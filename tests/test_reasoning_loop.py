import asyncio
import json

import pytest

from agent.loops import reasoning_loop as rl
from agent.loops.reasoning_loop import ReasoningLoop, ToolCallBudgetExceeded


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, data):
        self.content = [FakeContent(json.dumps(data))]


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def call_tool(self, name, arguments):
        await asyncio.sleep(0)
        self.calls.append((name, arguments))
        return FakeResult(self.responses[name])


def run(coro):
    return asyncio.run(coro)


def test_search_records_trace_with_rationale():
    session = FakeSession({"search": {"total": 3}})
    loop = ReasoningLoop(session=session, run_id="test-run")
    result = run(loop.search("raw_customers", rationale="resolve dataset URN"))
    assert result == {"total": 3}
    assert len(loop.trace) == 1
    assert loop.trace[0].tool == "search"
    assert loop.trace[0].rationale == "resolve dataset URN"
    assert "3" in loop.trace[0].result_summary


def test_get_lineage_passes_column_and_hops():
    session = FakeSession({"get_lineage": {"downstreams": {"total": 5}}})
    loop = ReasoningLoop(session=session, run_id="test-run", max_hops=3)
    run(loop.get_lineage("urn:li:dataset:x", rationale="scope column impact", column="cust_id"))
    name, args = session.calls[0]
    assert name == "get_lineage"
    assert args["column"] == "cust_id"
    assert args["max_hops"] == 3
    assert args["upstream"] is False


def test_get_lineage_upstream_uses_upstreams_key():
    session = FakeSession({"get_lineage": {"upstreams": {"total": 2}}})
    loop = ReasoningLoop(session=session, run_id="test-run")
    result = run(loop.get_lineage("urn:li:dataset:x", rationale="check origin", upstream=True))
    assert result == {"upstreams": {"total": 2}}
    assert "2 upstreams" in loop.trace[0].result_summary


def test_tool_call_budget_enforced():
    session = FakeSession({"search": {"total": 1}})
    loop = ReasoningLoop(session=session, run_id="test-run", max_tool_calls=2)
    run(loop.search("a", rationale="r1"))
    run(loop.search("b", rationale="r2"))
    coro = loop.search("c", rationale="r3")
    with pytest.raises(ToolCallBudgetExceeded):
        run(coro)


def test_save_document_passes_type_title_content_and_related_assets():
    session = FakeSession({"save_document": {"success": True, "urn": "urn:li:document:abc123"}})
    loop = ReasoningLoop(session=session, run_id="test-run")
    result = run(
        loop.save_document(
            "Decision",
            "Blast Radius: raw_customers.cust_id migration dossier",
            "# dossier markdown",
            rationale="persist migration dossier for reviewers",
            related_assets=["urn:li:dataset:x", "urn:li:dataset:y"],
            topics=["blast-radius"],
        )
    )
    assert result == {"success": True, "urn": "urn:li:document:abc123"}
    name, args = session.calls[0]
    assert name == "save_document"
    assert args["document_type"] == "Decision"
    assert args["title"] == "Blast Radius: raw_customers.cust_id migration dossier"
    assert args["content"] == "# dossier markdown"
    assert args["related_assets"] == ["urn:li:dataset:x", "urn:li:dataset:y"]
    assert args["topics"] == ["blast-radius"]
    assert "success=True" in loop.trace[0].result_summary


def test_save_document_omits_optional_args_when_not_given():
    session = FakeSession({"save_document": {"success": True, "urn": "urn:li:document:def456"}})
    loop = ReasoningLoop(session=session, run_id="test-run")
    run(loop.save_document("Note", "title", "content", rationale="r"))
    _, args = session.calls[0]
    assert "related_assets" not in args
    assert "topics" not in args


def test_write_trace_creates_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "TRACES_DIR", tmp_path)
    session = FakeSession({"search": {"total": 1}})
    loop = ReasoningLoop(session=session, run_id="test-run")
    run(loop.search("a", rationale="r1"))
    path = loop.write_trace()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["tool"] == "search"
    assert record["rationale"] == "r1"
