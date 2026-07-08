"""Unit tests for Loop 1 -- the Self-Correction Loop
(agent/loops/self_correction_loop.py) -- against fake generate_fn/verify_fn,
matching the style of tests/test_reasoning_loop.py.

agent/verify/ (VerificationOutcome, VerificationReport, verify_artifact) is
being built in parallel and may not exist on disk yet -- these tests never
import from it. Instead they define local fakes matching the exact contract
pinned in this phase's spec, and inject a fake `verify_fn` directly, proving
the retry / failure-evidence-injection / cap / tracing plumbing works
independent of the real verify module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from agent.loops import self_correction_loop as scl
from agent.loops.self_correction_loop import run_self_correction


@dataclass
class FakeVerificationOutcome:
    level: str
    passed: bool
    message: str
    raw_error: str | None = None


@dataclass
class FakeVerificationReport:
    artifact_path: str
    outcomes: list[FakeVerificationOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(o.passed for o in self.outcomes)

    @property
    def first_failure(self) -> FakeVerificationOutcome | None:
        return next((o for o in self.outcomes if not o.passed), None)


def _failing_report(raw_error: str) -> FakeVerificationReport:
    return FakeVerificationReport(
        artifact_path="models/staging/stg_customers.sql",
        outcomes=[FakeVerificationOutcome(level="V2_COMPILE", passed=False, message="compile failed", raw_error=raw_error)],
    )


def _passing_report() -> FakeVerificationReport:
    return FakeVerificationReport(
        artifact_path="models/staging/stg_customers.sql",
        outcomes=[
            FakeVerificationOutcome(level="V1_STATIC", passed=True, message="static check ok"),
            FakeVerificationOutcome(level="V2_COMPILE", passed=True, message="compile ok"),
        ],
    )


# --- retry + failure-evidence injection -------------------------------------


def test_retry_succeeds_on_second_attempt_and_injects_prior_raw_error(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    generate_calls: list[str | None] = []

    def fake_generate(failure_evidence):
        generate_calls.append(failure_evidence)
        return f"candidate content (attempt {len(generate_calls)})"

    verify_results = [_failing_report("column c.customer_id does not exist"), _passing_report()]

    def fake_verify(dbt_file_path, project_dir, levels):
        return verify_results.pop(0)

    result = run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
    )

    # (a) generate_fn called a second time
    assert len(generate_calls) == 2
    # (b) it received exactly the raw_error string from attempt 1's failure
    assert generate_calls[0] is None  # first attempt: no prior failure
    assert generate_calls[1] == "column c.customer_id does not exist"
    # (c) final_status == PASSED
    assert result.final_status == "PASSED"
    # (d) attempts has exactly 2 records
    assert len(result.attempts) == 2
    assert result.attempts[0].verification.passed is False
    assert result.attempts[1].verification.passed is True


def test_disk_write_happens_before_verify_is_called(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path / "traces")
    project_dir = tmp_path / "project"

    def fake_generate(failure_evidence):
        return "select 1 as cust_id"

    written_content_at_verify_time = {}

    def fake_verify(dbt_file_path, proj_dir, levels):
        target = __import__("pathlib").Path(proj_dir) / dbt_file_path
        written_content_at_verify_time["content"] = target.read_text()
        return _passing_report()

    run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(project_dir),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
    )

    assert written_content_at_verify_time["content"] == "select 1 as cust_id"


# --- cap at max_attempts -----------------------------------------------------


def test_always_failing_verify_stops_at_max_attempts_and_needs_human(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    generate_calls = []

    def fake_generate(failure_evidence):
        generate_calls.append(failure_evidence)
        return "still broken sql"

    def fake_verify(dbt_file_path, project_dir, levels):
        return _failing_report("still broken")

    result = run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
        max_attempts=3,
    )

    assert len(generate_calls) == 3
    assert len(result.attempts) == 3
    assert result.final_status == "NEEDS_HUMAN"
    assert all(not a.verification.passed for a in result.attempts)


def test_max_attempts_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    def fake_generate(failure_evidence):
        return "still broken sql"

    def fake_verify(dbt_file_path, project_dir, levels):
        return _failing_report("still broken")

    result = run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
        max_attempts=5,
    )

    assert len(result.attempts) == 5
    assert result.final_status == "NEEDS_HUMAN"


# --- tracing -----------------------------------------------------------------


def test_trace_file_written_with_one_line_per_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    def fake_generate(failure_evidence):
        return "candidate sql"

    verify_results = [_failing_report("boom"), _passing_report()]

    def fake_verify(dbt_file_path, project_dir, levels):
        return verify_results.pop(0)

    result = run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
    )

    trace_path = tmp_path / f"{result.run_id}.jsonl"
    assert trace_path.exists()

    lines = trace_path.read_text().strip().splitlines()
    assert len(lines) == 2

    record_1 = json.loads(lines[0])
    assert record_1["attempt_number"] == 1
    assert record_1["passed"] is False
    assert record_1["dbt_file_path"] == "models/staging/stg_customers.sql"
    assert record_1["first_failure_raw_error"] == "boom"

    record_2 = json.loads(lines[1])
    assert record_2["attempt_number"] == 2
    assert record_2["passed"] is True


def test_verification_levels_forwarded_to_verify_fn(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    captured_levels = []

    def fake_generate(failure_evidence):
        return "candidate sql"

    def fake_verify(dbt_file_path, project_dir, levels):
        captured_levels.append(levels)
        return _passing_report()

    run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
        verification_levels=["V1_STATIC"],
    )

    assert captured_levels == [["V1_STATIC"]]


def test_lazy_import_default_verify_fn_is_not_required_when_injected(tmp_path, monkeypatch):
    """Proves this module doesn't eagerly import agent.verify at module load
    time -- only inside run_self_correction, and only when verify_fn is not
    supplied. Since we always supply a fake verify_fn here, this must work
    even if agent/verify/harness.py doesn't exist yet."""
    monkeypatch.setattr(scl, "TRACES_DIR", tmp_path)

    def fake_generate(failure_evidence):
        return "candidate sql"

    def fake_verify(dbt_file_path, project_dir, levels):
        return _passing_report()

    result = run_self_correction(
        dbt_file_path="models/staging/stg_customers.sql",
        project_dir=str(tmp_path / "project"),
        generate_fn=fake_generate,
        verify_fn=fake_verify,
    )

    assert result.final_status == "PASSED"
