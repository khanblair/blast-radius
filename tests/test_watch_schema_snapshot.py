import asyncio
import json

from agent.loops.reasoning_loop import ReasoningLoop
from agent.watch.models import SchemaSnapshot
from agent.watch.schema_snapshot import capture_snapshot, diff_snapshots, load_snapshot, save_snapshot


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeResult:
    def __init__(self, data):
        self.content = [FakeContent(json.dumps(data))]


class FakeSession:
    """Same shape as tests/test_reasoning_loop.py's FakeSession -- maps tool
    name to a single canned response."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return FakeResult(self.responses[name])


def run(coro):
    return asyncio.run(coro)


def col(name, type_="varchar"):
    return {"name": name, "type": type_}


# ---------------------------------------------------------------------------
# capture_snapshot
# ---------------------------------------------------------------------------


def test_capture_snapshot_resolves_urn_and_maps_fields():
    session = FakeSession(
        {
            "search": {
                "searchResults": [
                    {"entity": {"urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,public.raw_customers,PROD)"}}
                ]
            },
            "list_schema_fields": {
                "urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,public.raw_customers,PROD)",
                "totalFields": 2,
                "fields": [
                    {"fieldPath": "cust_id", "nativeDataType": "varchar"},
                    {"fieldPath": "email", "nativeDataType": "varchar"},
                ],
            },
        }
    )
    loop = ReasoningLoop(session=session, run_id="test-watch")

    snapshot = run(capture_snapshot(loop, "raw_customers", "public", "postgres", captured_at="2026-07-08T00:00:00+00:00"))

    assert snapshot.table == "raw_customers"
    assert snapshot.captured_at == "2026-07-08T00:00:00+00:00"
    assert snapshot.columns == [
        {"name": "cust_id", "type": "varchar"},
        {"name": "email", "type": "varchar"},
    ]
    tool_names = [name for name, _ in session.calls]
    assert tool_names == ["search", "list_schema_fields"]


# ---------------------------------------------------------------------------
# save_snapshot / load_snapshot
# ---------------------------------------------------------------------------


def test_save_and_load_snapshot_round_trip(tmp_path):
    snapshot = SchemaSnapshot(
        table="raw_customers",
        columns=[col("cust_id"), col("email")],
        captured_at="2026-07-08T00:00:00+00:00",
    )
    path = tmp_path / "raw_customers.json"

    save_snapshot(snapshot, path)
    loaded = load_snapshot(path)

    assert loaded == snapshot


def test_save_snapshot_creates_parent_dirs(tmp_path):
    snapshot = SchemaSnapshot(table="t", columns=[], captured_at="2026-07-08T00:00:00+00:00")
    path = tmp_path / "nested" / "dir" / "t.json"

    save_snapshot(snapshot, path)

    assert path.exists()
    assert load_snapshot(path) == snapshot


def test_load_snapshot_returns_none_for_missing_file(tmp_path):
    assert load_snapshot(tmp_path / "does_not_exist.json") is None


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------


def snapshot(columns, table="raw_customers"):
    return SchemaSnapshot(table=table, columns=columns, captured_at="2026-07-08T00:00:00+00:00")


def test_diff_no_changes_returns_empty_list():
    old = snapshot([col("cust_id"), col("email")])
    new = snapshot([col("cust_id"), col("email")])

    assert diff_snapshots(old, new) == []


def test_diff_single_add_column():
    old = snapshot([col("cust_id")])
    new = snapshot([col("cust_id"), col("signup_date")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 1
    change = changes[0]
    assert change.change_type == "add_column"
    assert change.old_column is None
    assert change.new_column == "signup_date"
    assert change.table == "raw_customers"
    assert "signup_date" in change.evidence


def test_diff_single_drop_column():
    old = snapshot([col("cust_id"), col("fax_number")])
    new = snapshot([col("cust_id")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 1
    change = changes[0]
    assert change.change_type == "drop_column"
    assert change.old_column == "fax_number"
    assert change.new_column is None
    assert "fax_number" in change.evidence


def test_diff_single_possible_rename():
    old = snapshot([col("cust_id"), col("email")])
    new = snapshot([col("customer_id"), col("email")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 1
    change = changes[0]
    assert change.change_type == "possible_rename"
    assert change.old_column == "cust_id"
    assert change.new_column == "customer_id"
    # evidence must be honest that this is a guess, not a certainty
    assert "heuristic" in change.evidence.lower() or "guess" in change.evidence.lower()


def test_diff_ambiguous_multi_change_does_not_guess_pairing():
    # two disappeared, one appeared -- must NOT be paired into a rename
    old = snapshot([col("cust_id"), col("fax_number"), col("email")])
    new = snapshot([col("email"), col("signup_date")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 3
    drops = {c.old_column for c in changes if c.change_type == "drop_column"}
    adds = {c.new_column for c in changes if c.change_type == "add_column"}
    assert drops == {"cust_id", "fax_number"}
    assert adds == {"signup_date"}
    assert all(c.change_type != "possible_rename" for c in changes)


def test_diff_ambiguous_multi_change_one_disappeared_two_appeared():
    # one disappeared, two appeared -- counts don't match 1-and-1 either, so
    # this must also NOT be paired into a rename.
    old = snapshot([col("cust_id")])
    new = snapshot([col("customer_id"), col("email")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 3
    drops = {(c.change_type, c.old_column) for c in changes if c.change_type == "drop_column"}
    adds = {(c.change_type, c.new_column) for c in changes if c.change_type == "add_column"}
    assert drops == {("drop_column", "cust_id")}
    assert adds == {("add_column", "customer_id"), ("add_column", "email")}
    assert all(c.change_type != "possible_rename" for c in changes)


def test_diff_empty_to_populated_reports_independent_adds():
    old = snapshot([])
    new = snapshot([col("cust_id"), col("email")])

    changes = diff_snapshots(old, new)

    assert len(changes) == 2
    assert all(c.change_type == "add_column" for c in changes)
    assert {c.new_column for c in changes} == {"cust_id", "email"}


def test_diff_populated_to_empty_reports_independent_drops():
    old = snapshot([col("cust_id"), col("email")])
    new = snapshot([])

    changes = diff_snapshots(old, new)

    assert len(changes) == 2
    assert all(c.change_type == "drop_column" for c in changes)
    assert {c.old_column for c in changes} == {"cust_id", "email"}


def test_diff_empty_to_empty_returns_empty_list():
    old = snapshot([])
    new = snapshot([])

    assert diff_snapshots(old, new) == []
