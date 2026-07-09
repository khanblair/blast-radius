"""Unit tests for the Dossier renderer (agent/dossier/renderer.py) against
fabricated AssessmentResult/NarrativeResult/MigrationDecision/
SelfCorrectionResult objects, matching the fabrication style of
tests/test_decision_engine.py and tests/test_narrative_builder.py.
"""
from __future__ import annotations

from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, ORIGIN_HARD_BREAK, AssessmentResult, AssetAssessment
from agent.decision.models import (
    AUTO_APPROVED,
    BREAKING,
    HUMAN_CONFIRMED,
    NO_MIGRATION_NEEDED,
    MigrationDecision,
    RejectedStrategy,
    StrategyOption,
)
from agent.dossier.renderer import render_dossier
from agent.loops.self_correction_loop import NEEDS_HUMAN, PASSED, AttemptRecord, SelfCorrectionResult
from agent.narrative.models import AssetNarrative, NarrativeResult
from agent.verify.models import V1_STATIC, V2_COMPILE, VerificationOutcome, VerificationReport


# --- fabrication helpers -----------------------------------------------------


def _asset(**overrides):
    defaults = dict(
        urn="urn:li:dataset:x",
        name="x",
        compile_status=ORIGIN_HARD_BREAK,
        select_star_exposure=False,
        evidence=[],
        hop=1,
        usage_count=0,
        is_dashboard_exposed=False,
        owners=[],
        has_business_owner=False,
        severity_score=0.0,
        dbt_file_path=None,
    )
    defaults.update(overrides)
    return AssetAssessment(**defaults)


def _assessment():
    origin = _asset(
        name="stg_customers",
        compile_status=ORIGIN_HARD_BREAK,
        evidence=["models/staging/stg_customers.sql:4: cust_id,"],
        hop=1,
        usage_count=3,
        severity_score=42.0,
        dbt_file_path="models/staging/stg_customers.sql",
    )
    cascade = _asset(
        urn="urn:li:dataset:fct_revenue",
        name="fct_revenue",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=True,
        evidence=["models/marts/fct_revenue.sql:12: c.*"],
        hop=2,
        usage_count=12,
        is_dashboard_exposed=True,
        owners=["urn:li:corpuser:jchen"],
        severity_score=88.0,
    )
    safe = _asset(
        urn="urn:li:dataset:fct_orders",
        name="fct_orders",
        compile_status=NOT_IMPACTED,
        severity_score=0.0,
    )
    return AssessmentResult(
        changed_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)",
        changed_column="cust_id",
        scanned=[origin, cascade, safe],
        deepest_hop=2,
    )


def _narrative():
    return NarrativeResult(
        changed_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.raw_customers,PROD)",
        changed_column="cust_id",
        narratives=[
            AssetNarrative(
                urn="urn:li:dataset:x",
                name="stg_customers",
                narrative_text="stg_customers directly references the changed column and will fail to compile.",
                evidence_cited=["models/staging/stg_customers.sql:4: cust_id,"],
                break_mode="HARD_BREAK",
                source="template",
            ),
            AssetNarrative(
                urn="urn:li:dataset:fct_revenue",
                name="fct_revenue",
                narrative_text="fct_revenue is a loud hard break today, but its SELECT * means a careless fix could make it fail silently.",
                evidence_cited=["models/marts/fct_revenue.sql:12: c.*"],
                break_mode="HARD_BREAK",
                source="llm",
            ),
        ],
        safe_summary="fct_orders is confirmed safe -- no reference to the changed column.",
    )


def _decision(confirmation_mode=HUMAN_CONFIRMED, human_confirmed=True):
    options = [
        StrategyOption("A", "Direct patch", "Patch every consumer in one PR.", "Clean and atomic, but big-bang risk."),
        StrategyOption("B", "Bridge migration", "Compatibility view aliasing old -> new.", "Zero-downtime, more moving parts."),
        StrategyOption("C", "Defer & deprecate", "Recommend a deprecation cycle.", "Avoids risk, doesn't solve it today."),
    ]
    rejected = [
        RejectedStrategy("A", "fct_revenue is dashboard-exposed -- a big-bang patch risks a visible outage."),
        RejectedStrategy("C", "blast radius is small enough to fix now."),
    ]
    return MigrationDecision(
        decision_type=BREAKING,
        rationale="fct_revenue is dashboard-exposed -- recommend a bridge migration.",
        options=options,
        recommended_strategy="B",
        rejected=rejected,
        human_confirmed=human_confirmed,
        confirmed_strategy="B",
        confirmation_mode=confirmation_mode,
    )


ORIGINAL_SQL = "select\n    cust_id,\n    name\nfrom {{ source('warehouse', 'raw_customers') }}\n"
ATTEMPT_1_SQL = "select\n    customer_id,\n    name\nfrom {{ source('warehosue', 'raw_customers') }}\n"  # typo'd source, fails
ATTEMPT_2_SQL = "select\n    customer_id as cust_id,\n    name\nfrom {{ source('warehouse', 'raw_customers') }}\n"


def _failing_verification(raw_error: str) -> VerificationReport:
    return VerificationReport(
        artifact_path="models/staging/stg_customers.sql",
        outcomes=[
            VerificationOutcome(level=V1_STATIC, passed=True, message="parses fine"),
            VerificationOutcome(level=V2_COMPILE, passed=False, message="dbt compile failed", raw_error=raw_error),
        ],
    )


def _passing_verification() -> VerificationReport:
    return VerificationReport(
        artifact_path="models/staging/stg_customers.sql",
        outcomes=[
            VerificationOutcome(level=V1_STATIC, passed=True, message="parses fine"),
            VerificationOutcome(level=V2_COMPILE, passed=True, message="dbt compile succeeded"),
        ],
    )


def _self_correction_passed_after_retry() -> SelfCorrectionResult:
    """2 attempts: first fails, second passes -- exercises the
    diff-across-attempts logic (first attempt's candidate vs last attempt's
    candidate) and the Verification Gauntlet's raw_error-on-failure path."""
    return SelfCorrectionResult(
        dbt_file_path="models/staging/stg_customers.sql",
        attempts=[
            AttemptRecord(
                attempt_number=1,
                candidate_content=ATTEMPT_1_SQL,
                verification=_failing_verification("relation \"warehosue.raw_customers\" does not exist"),
            ),
            AttemptRecord(
                attempt_number=2,
                candidate_content=ATTEMPT_2_SQL,
                verification=_passing_verification(),
            ),
        ],
        final_status=PASSED,
        run_id="selfcorrect-test1234",
    )


def _self_correction_needs_human() -> SelfCorrectionResult:
    return SelfCorrectionResult(
        dbt_file_path="models/staging/stg_customers.sql",
        attempts=[
            AttemptRecord(
                attempt_number=1,
                candidate_content=ATTEMPT_1_SQL,
                verification=_failing_verification("relation \"warehosue.raw_customers\" does not exist"),
            ),
            AttemptRecord(
                attempt_number=2,
                candidate_content=ATTEMPT_1_SQL,
                verification=_failing_verification("relation \"warehosue.raw_customers\" does not exist"),
            ),
        ],
        final_status=NEEDS_HUMAN,
        run_id="selfcorrect-test5678",
    )


# --- all five sections present -----------------------------------------------


def test_all_five_sections_present_when_self_correction_passed():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "## 1. Impact Assessment" in dossier
    assert "## 2. Causal Narratives" in dossier
    assert "## 3. Migration Decision" in dossier
    assert "## 4. Generated Code" in dossier
    assert "## 5. Verification Gauntlet" in dossier


def test_impact_assessment_section_reflects_severity_matrix_facts():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "stg_customers" in dossier
    assert "fct_revenue" in dossier
    assert "HARD_BREAK" in dossier
    assert "deepest hop" in dossier.lower() or "Deepest hop" in dossier
    assert "2" in dossier  # deepest_hop value present somewhere


def test_causal_narratives_section_cites_break_mode_and_evidence():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "directly references the changed column" in dossier
    assert "models/staging/stg_customers.sql:4: cust_id," in dossier
    assert "models/marts/fct_revenue.sql:12: c.*" in dossier
    assert "fct_orders is confirmed safe" in dossier


def test_migration_decision_section_lists_options_recommendation_and_rejections():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "MIGRATION DECISION" in dossier or "Migration Decision" in dossier
    assert "BREAKING" in dossier
    assert "Bridge migration" in dossier
    assert "(RECOMMENDED)" in dossier
    assert "dashboard-exposed" in dossier
    assert "blast radius is small enough to fix now." in dossier


def test_migration_decision_section_includes_confirmation_provenance():
    human_confirmed = render_dossier(
        _assessment(), _narrative(), _decision(confirmation_mode=HUMAN_CONFIRMED, human_confirmed=True),
        _self_correction_passed_after_retry(),
    )
    assert "HUMAN_CONFIRMED" in human_confirmed
    assert "human_confirmed: `True`" in human_confirmed

    auto_approved = render_dossier(
        _assessment(), _narrative(), _decision(confirmation_mode=AUTO_APPROVED, human_confirmed=False),
        _self_correction_passed_after_retry(),
    )
    assert "AUTO_APPROVED" in auto_approved
    assert "human_confirmed: `False`" in auto_approved
    assert "NOT a human sign-off" in auto_approved or "not a human sign-off" in auto_approved.lower()


# --- generated code diff (attempt-to-attempt) --------------------------------


def test_generated_code_diffs_first_attempt_against_last_attempt():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "```diff" in dossier
    # unified diff must show the old (attempt 1) line being removed...
    assert "-    customer_id," in dossier
    # ...and the final (attempt 2) line being added
    assert "+    customer_id as cust_id," in dossier


def test_generated_code_diffs_against_original_when_only_one_attempt():
    one_attempt = SelfCorrectionResult(
        dbt_file_path="models/staging/stg_customers.sql",
        attempts=[AttemptRecord(attempt_number=1, candidate_content=ATTEMPT_2_SQL, verification=_passing_verification())],
        final_status=PASSED,
        run_id="selfcorrect-onehop",
    )

    dossier = render_dossier(
        _assessment(), _narrative(), _decision(), one_attempt, original_content=ORIGINAL_SQL
    )

    assert "pre-patch original -> attempt 1" in dossier
    assert "-    cust_id," in dossier
    assert "+    customer_id as cust_id," in dossier


# --- verification gauntlet ----------------------------------------------------


def test_verification_gauntlet_shows_every_attempt_and_raw_error_on_failure():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "Attempt 1: FAIL" in dossier
    assert "Attempt 2: PASS" in dossier
    assert "relation \"warehosue.raw_customers\" does not exist" in dossier
    assert "[V1_STATIC]" in dossier
    assert "[V2_COMPILE]" in dossier


# --- PASSED vs NEEDS_HUMAN render visibly differently ------------------------


def test_passed_dossier_reads_as_a_delivery():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())

    assert "STATUS: PASSED" in dossier
    assert "READY FOR REVIEW" in dossier
    assert "NEEDS_HUMAN" not in dossier.split("---")[0]  # not in the header banner


def test_needs_human_dossier_reads_as_a_request_for_help_not_a_delivery():
    dossier = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_needs_human())

    assert "STATUS: NEEDS_HUMAN" in dossier
    assert "NOT A DELIVERY" in dossier
    assert "REQUEST FOR HELP" in dossier
    assert "Do NOT merge" in dossier
    assert "READY FOR REVIEW" not in dossier


def test_passed_and_needs_human_dossiers_have_different_headers():
    passed = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_passed_after_retry())
    needs_human = render_dossier(_assessment(), _narrative(), _decision(), _self_correction_needs_human())

    passed_header = passed.split("---", 1)[0]
    needs_human_header = needs_human.split("---", 1)[0]
    assert passed_header != needs_human_header


def test_passed_with_zero_attempts_renders_as_needs_human_not_a_delivery():
    # Defense-in-depth regression coverage: SelfCorrectionResult.final_status
    # defaults to PASSED, so a result with zero recorded attempts (which
    # run_self_correction itself now refuses to produce) must never render
    # as a confident delivery banner if it reaches this renderer some other
    # way -- that would be a false PASSED with nothing actually verified.
    inconsistent_result = SelfCorrectionResult(
        dbt_file_path="models/staging/stg_customers.sql",
        attempts=[],
        final_status=PASSED,
        run_id="selfcorrect-inconsistent",
    )

    dossier = render_dossier(_assessment(), _narrative(), _decision(), inconsistent_result)

    assert "STATUS: NEEDS_HUMAN" in dossier
    assert "NOT A DELIVERY" in dossier
    assert "Do NOT merge" in dossier
    assert "READY FOR REVIEW" not in dossier


# --- fail-honest multi-origin handling ---------------------------------------


def test_unhandled_origin_names_forces_needs_human_even_when_self_correction_passed():
    # Regression coverage: codegen/verification is single-file by design, so
    # a change with more than one true origin only ever gets one of them
    # patched. Reporting a confident PASSED for the whole change while a
    # second origin's break sits unpatched would be a false trust signal --
    # unhandled_origin_names must force NEEDS_HUMAN even when the one patch
    # that DID run passed every verification level.
    dossier = render_dossier(
        _assessment(),
        _narrative(),
        _decision(),
        _self_correction_passed_after_retry(),
        unhandled_origin_names=["stg_other_customers"],
    )

    assert "STATUS: NEEDS_HUMAN" in dossier
    assert "NOT A DELIVERY" in dossier
    assert "stg_other_customers" in dossier
    assert "Do NOT merge" in dossier
    assert "READY FOR REVIEW" not in dossier


def test_unhandled_origin_names_with_no_self_correction_still_names_them():
    # A BREAKING decision can have multiple origins but codegen might still
    # be skipped for other reasons -- the unhandled-origins banner must not
    # assume self_correction is present.
    dossier = render_dossier(
        _assessment(),
        _narrative(),
        _decision(),
        self_correction=None,
        unhandled_origin_names=["stg_other_customers", "stg_yet_another"],
    )

    assert "STATUS: NEEDS_HUMAN" in dossier
    assert "stg_other_customers" in dossier
    assert "stg_yet_another" in dossier


# --- no-codegen path (NO_MIGRATION_NEEDED / ADDITIVE) ------------------------


def test_no_migration_needed_dossier_omits_code_and_verification_sections():
    no_migration_decision = MigrationDecision(decision_type=NO_MIGRATION_NEEDED, rationale="0 affected assets.")
    dossier = render_dossier(_assessment(), _narrative(), no_migration_decision, self_correction=None)

    assert "## 1. Impact Assessment" in dossier
    assert "## 2. Causal Narratives" in dossier
    assert "## 3. Migration Decision" in dossier
    assert "## 4. Generated Code" not in dossier
    assert "## 5. Verification Gauntlet" not in dossier
    assert "ASSESSMENT ONLY" in dossier
    assert "NO_MIGRATION_NEEDED" in dossier


def test_deferred_breaking_dossier_does_not_claim_no_code_change_required():
    # Strategy C (defer): a fix genuinely IS needed, just not generated yet
    # pending owner sign-off -- the banner must say so, not claim "no code
    # change required" the way NO_MIGRATION_NEEDED/ADDITIVE correctly do.
    deferred_decision = MigrationDecision(
        decision_type=BREAKING,
        rationale="Blast radius too large for a same-day fix.",
        options=[StrategyOption("C", "Defer & deprecate", "...", "...")],
        recommended_strategy="C",
        rejected=[RejectedStrategy("A", "..."), RejectedStrategy("B", "...")],
    )
    dossier = render_dossier(_assessment(), _narrative(), deferred_decision, self_correction=None)

    assert "## 1. Impact Assessment" in dossier
    assert "## 4. Generated Code" not in dossier
    assert "## 5. Verification Gauntlet" not in dossier
    assert "NO CODE CHANGE REQUIRED" not in dossier
    assert "DEFERRED" in dossier
    assert "strategy C" in dossier


def test_unrecognized_decision_type_does_not_fall_through_to_assessment_only():
    # Defense-in-depth regression coverage: decision_type is a bare str, not
    # a closed Enum (agent/decision/models.py). A future bug that produces
    # an unrecognized value with self_correction=None must not silently
    # read as "ASSESSMENT ONLY -- NO CODE CHANGE REQUIRED" -- that would be
    # a false assurance that nothing needs attention.
    garbage_decision = MigrationDecision(decision_type="SOMETHING_UNEXPECTED", rationale="...")

    dossier = render_dossier(_assessment(), _narrative(), garbage_decision, self_correction=None)

    assert "ASSESSMENT ONLY" not in dossier
    assert "NO CODE CHANGE REQUIRED" not in dossier
    assert "STATUS: UNKNOWN" in dossier
    assert "SOMETHING_UNEXPECTED" in dossier
    assert "do not assume" in dossier.lower()
