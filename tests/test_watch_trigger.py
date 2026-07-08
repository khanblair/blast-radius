import sys
import types

from agent.watch.models import DetectedChange
from agent.watch.trigger import run_watch_cycle


def change(change_type, old_column, new_column, table="raw_customers"):
    return DetectedChange(
        table=table,
        change_type=change_type,
        old_column=old_column,
        new_column=new_column,
        evidence="test evidence",
    )


class RecordingPipeline:
    """A fake pipeline_fn spy: records every call's positional args and
    returns a distinguishable, deterministic result per call."""

    def __init__(self):
        self.calls = []

    def __call__(self, table, old_column, new_column, change_type):
        self.calls.append((table, old_column, new_column, change_type))
        return {"table": table, "old_column": old_column, "new_column": new_column, "change_type": change_type}


def test_possible_rename_triggers_pipeline_with_correct_args():
    pipeline = RecordingPipeline()
    rename = change("possible_rename", "cust_id", "customer_id")

    triggered = run_watch_cycle([rename], pipeline_fn=pipeline)

    assert pipeline.calls == [("raw_customers", "cust_id", "customer_id", "possible_rename")]
    assert len(triggered) == 1
    assert triggered[0]["change"] is rename
    assert triggered[0]["result"] == {
        "table": "raw_customers",
        "old_column": "cust_id",
        "new_column": "customer_id",
        "change_type": "possible_rename",
    }


def test_add_column_alone_does_not_trigger_pipeline():
    pipeline = RecordingPipeline()
    add = change("add_column", None, "signup_date")

    triggered = run_watch_cycle([add], pipeline_fn=pipeline)

    assert pipeline.calls == []
    assert triggered == []


def test_drop_column_alone_does_not_trigger_pipeline():
    pipeline = RecordingPipeline()
    drop = change("drop_column", "fax_number", None)

    triggered = run_watch_cycle([drop], pipeline_fn=pipeline)

    assert pipeline.calls == []
    assert triggered == []


def test_mixed_changes_only_triggers_the_rename():
    pipeline = RecordingPipeline()
    rename = change("possible_rename", "cust_id", "customer_id")
    add = change("add_column", None, "signup_date")
    drop = change("drop_column", "fax_number", None)

    triggered = run_watch_cycle([add, rename, drop], pipeline_fn=pipeline)

    assert pipeline.calls == [("raw_customers", "cust_id", "customer_id", "possible_rename")]
    assert len(triggered) == 1
    assert triggered[0]["change"] is rename


def test_empty_changes_list_with_injected_pipeline_returns_empty():
    pipeline = RecordingPipeline()

    triggered = run_watch_cycle([], pipeline_fn=pipeline)

    assert triggered == []
    assert pipeline.calls == []


def test_empty_changes_list_with_default_pipeline_never_imports_dossier():
    """The default pipeline_fn lazily imports agent.dossier.pipeline -- but
    only when it is actually called. With no actionable changes, it must
    never be invoked, so this must succeed even though agent/dossier/pipeline.py
    does not exist yet (Phase 7 is a parallel, separate build)."""
    assert "agent.dossier.pipeline" not in sys.modules

    triggered = run_watch_cycle([])

    assert triggered == []
    assert "agent.dossier.pipeline" not in sys.modules


def test_add_and_drop_only_changes_with_default_pipeline_never_imports_dossier():
    add = change("add_column", None, "signup_date")
    drop = change("drop_column", "fax_number", None)

    assert "agent.dossier.pipeline" not in sys.modules

    triggered = run_watch_cycle([add, drop])

    assert triggered == []
    assert "agent.dossier.pipeline" not in sys.modules


def test_default_pipeline_fn_never_auto_approves_or_creates_live_pr(monkeypatch):
    """Proves the hardcoded safety kwargs on the real (lazily-imported)
    default path: an autonomously-triggered detection must never
    auto-approve a strategy or create a live PR unattended. We stand in a
    fake `agent.dossier.pipeline` module (via sys.modules) since the real
    one is a parallel, separate build that may not exist yet -- this
    exercises the actual default-path wrapper, not just an injected fake."""
    calls = []

    def fake_run_full_pipeline(table, old_column, new_column, change_type, **kwargs):
        calls.append((table, old_column, new_column, change_type, kwargs))
        return {"ok": True}

    fake_module = types.ModuleType("agent.dossier.pipeline")
    fake_module.run_full_pipeline = fake_run_full_pipeline
    monkeypatch.setitem(sys.modules, "agent.dossier.pipeline", fake_module)

    rename = change("possible_rename", "cust_id", "customer_id")
    triggered = run_watch_cycle([rename])  # pipeline_fn=None -> real default path

    assert len(calls) == 1
    table, old_column, new_column, change_type, kwargs = calls[0]
    assert (table, old_column, new_column, change_type) == ("raw_customers", "cust_id", "customer_id", "possible_rename")
    assert kwargs == {"auto_approve_decision": False, "create_pr_live": False}
    assert triggered == [{"change": rename, "result": {"ok": True}}]
