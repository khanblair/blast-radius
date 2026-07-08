from agent.watch.outcome import read_outcomes, record_outcome


def test_read_outcomes_returns_empty_list_for_missing_file(tmp_path):
    assert read_outcomes(tmp_path / "does_not_exist.jsonl") == []


def test_record_and_read_single_outcome_round_trip(tmp_path):
    log_path = tmp_path / "outcomes.jsonl"
    entry = {
        "timestamp": "2026-07-08T00:00:00+00:00",
        "table": "raw_customers",
        "change_type": "possible_rename",
        "old_column": "cust_id",
        "new_column": "customer_id",
        "pipeline_result": {"status": "dossier_generated"},
    }

    record_outcome(entry, log_path)

    assert read_outcomes(log_path) == [entry]


def test_record_outcome_creates_parent_dirs(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "outcomes.jsonl"
    entry = {"timestamp": "2026-07-08T00:00:00+00:00", "table": "t"}

    record_outcome(entry, log_path)

    assert log_path.exists()
    assert read_outcomes(log_path) == [entry]


def test_multiple_appended_outcomes_read_back_in_order(tmp_path):
    log_path = tmp_path / "outcomes.jsonl"
    first = {"timestamp": "2026-07-08T00:00:00+00:00", "table": "raw_customers", "change_type": "possible_rename"}
    second = {"timestamp": "2026-07-08T01:00:00+00:00", "table": "raw_orders", "change_type": "add_column"}
    third = {"timestamp": "2026-07-08T02:00:00+00:00", "table": "raw_customers", "change_type": "drop_column"}

    record_outcome(first, log_path)
    record_outcome(second, log_path)
    record_outcome(third, log_path)

    assert read_outcomes(log_path) == [first, second, third]
