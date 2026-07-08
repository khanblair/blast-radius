from agent.verify.models import V1_STATIC, V2_COMPILE, VerificationOutcome, VerificationReport


def test_report_with_no_outcomes_has_not_passed():
    # An empty report is not a vacuous pass -- nothing was actually checked.
    report = VerificationReport(artifact_path="models/staging/stg_orders.sql")
    assert report.passed is False
    assert report.first_failure is None


def test_report_passed_when_all_outcomes_passed():
    report = VerificationReport(
        artifact_path="models/staging/stg_orders.sql",
        outcomes=[
            VerificationOutcome(level=V1_STATIC, passed=True, message="ok"),
            VerificationOutcome(level=V2_COMPILE, passed=True, message="ok"),
        ],
    )
    assert report.passed is True
    assert report.first_failure is None


def test_report_not_passed_when_any_outcome_failed():
    report = VerificationReport(
        artifact_path="models/staging/stg_orders.sql",
        outcomes=[
            VerificationOutcome(level=V1_STATIC, passed=True, message="ok"),
            VerificationOutcome(level=V2_COMPILE, passed=False, message="bad", raw_error="boom"),
        ],
    )
    assert report.passed is False


def test_first_failure_returns_first_failing_outcome_in_order():
    failing = VerificationOutcome(level=V2_COMPILE, passed=False, message="bad", raw_error="boom")
    report = VerificationReport(
        artifact_path="models/staging/stg_orders.sql",
        outcomes=[
            VerificationOutcome(level=V1_STATIC, passed=True, message="ok"),
            failing,
        ],
    )
    assert report.first_failure is failing


def test_verification_outcome_raw_error_defaults_to_none():
    outcome = VerificationOutcome(level=V1_STATIC, passed=True, message="ok")
    assert outcome.raw_error is None
