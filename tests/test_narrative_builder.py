"""Unit tests for the Narrative Builder (agent/narrative/builder.py) against
fabricated AssetAssessment/AssessmentResult objects, matching the style of
tests/test_severity.py.

These confirm: the prompt/output actually incorporates the real evidence
strings and facts computed by the Assessment Engine, nothing is invented that
isn't in those facts, UNAFFECTED assets are excluded from `narratives` (but
summarized separately), and the no-LLM-configured path produces coherent
fallback prose rather than erroring.
"""
from __future__ import annotations

from agent.assessment.models import (
    CASCADE_HARD_BREAK,
    NOT_IMPACTED,
    ORIGIN_HARD_BREAK,
    AssessmentResult,
    AssetAssessment,
)
from agent.narrative.builder import build_narratives
from agent.narrative.llm_client import PROVIDER_API_KEY_ENV, build_llm_client


def _clear_all_provider_keys(monkeypatch):
    for env_var in PROVIDER_API_KEY_ENV.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


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
    )
    defaults.update(overrides)
    return AssetAssessment(**defaults)


def _fake_llm_client(captured_prompts):
    def fake_generate(system, user):
        captured_prompts.append((system, user))
        return f"LLM NARRATIVE for prompt containing: {user.splitlines()[1]}"

    return build_llm_client(provider="anthropic", generate_fn=fake_generate)


# --- exclusion / inclusion of assets ----------------------------------------


def test_only_affected_assets_get_narratives():
    hard = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, evidence=["stg_customers.sql:4: cust_id,"])
    safe = _asset(name="fct_orders", compile_status=NOT_IMPACTED)
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[hard, safe], deepest_hop=2)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client([]))

    names = {n.name for n in narrative_result.narratives}
    assert names == {"stg_customers"}
    assert "fct_orders" not in names


def test_safe_summary_names_unaffected_assets():
    hard = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK)
    safe1 = _asset(name="fct_orders", compile_status=NOT_IMPACTED)
    safe2 = _asset(name="stg_payments", compile_status=NOT_IMPACTED)
    result = AssessmentResult(
        changed_urn="urn:root", changed_column="cust_id", scanned=[hard, safe1, safe2], deepest_hop=1
    )

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client([]))

    assert narrative_result.safe_summary is not None
    assert "fct_orders" in narrative_result.safe_summary
    assert "stg_payments" in narrative_result.safe_summary


def test_safe_summary_is_none_when_everything_affected():
    hard = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK)
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[hard], deepest_hop=1)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client([]))

    assert narrative_result.safe_summary is None


# --- facts flow into the prompt / evidence_cited ----------------------------


def test_prompt_incorporates_real_evidence_and_facts():
    asset = _asset(
        name="stg_customers",
        compile_status=ORIGIN_HARD_BREAK,
        evidence=["models/staging/stg_customers.sql:4: cust_id,"],
        hop=1,
        usage_count=7,
        is_dashboard_exposed=True,
        owners=["urn:li:corpuser:jchen"],
    )
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=1)

    captured = []
    build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client(captured))

    assert len(captured) == 1
    _, user_prompt = captured[0]
    assert "models/staging/stg_customers.sql:4: cust_id," in user_prompt
    assert "usage_count (queries on record): 7" in user_prompt
    assert "is_dashboard_exposed: True" in user_prompt
    assert "urn:li:corpuser:jchen" in user_prompt
    assert "raw_customers.cust_id" in user_prompt


def test_evidence_cited_matches_asset_evidence_exactly():
    asset = _asset(name="fct_revenue", compile_status=CASCADE_HARD_BREAK, evidence=["a.sql:1: foo", "a.sql:12: c.*"])
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=2)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client([]))

    assert narrative_result.narratives[0].evidence_cited == ["a.sql:1: foo", "a.sql:12: c.*"]


def test_llm_narrative_source_is_llm_when_client_succeeds():
    asset = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK)
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=1)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=_fake_llm_client([]))

    assert narrative_result.narratives[0].source == "llm"


def test_llm_failure_falls_back_to_template_for_that_asset():
    asset = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, evidence=["stg_customers.sql:4: cust_id,"])
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=1)

    def raising_generate(system, user):
        raise RuntimeError("simulated transient API failure")

    client = build_llm_client(provider="anthropic", generate_fn=raising_generate)
    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=client)

    narrative = narrative_result.narratives[0]
    assert narrative.source == "template"
    assert "stg_customers.sql:4: cust_id," in narrative.narrative_text


def test_llm_empty_string_response_falls_back_to_template_not_blank_llm_text():
    # Regression coverage for a confirmed bug: an empty-string (not None) LLM
    # response used to bypass the template fallback entirely (the guard was
    # `if text is None`, and "" is not None), shipping narrative_text=""
    # mislabeled source="llm" instead of falling back to the template.
    asset = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, evidence=["stg_customers.sql:4: cust_id,"])
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=1)

    def blank_generate(system, user):
        return ""

    client = build_llm_client(provider="anthropic", generate_fn=blank_generate)
    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=client)

    narrative = narrative_result.narratives[0]
    assert narrative.source == "template"
    assert narrative.narrative_text  # non-empty
    assert "stg_customers.sql:4: cust_id," in narrative.narrative_text


# --- template fallback path (no LLM configured) -----------------------------


def test_template_fallback_used_when_no_llm_client_given(monkeypatch):
    _clear_all_provider_keys(monkeypatch)  # force the no-key path regardless of this machine's actual .env
    asset = _asset(
        name="stg_customers",
        compile_status=ORIGIN_HARD_BREAK,
        evidence=["models/staging/stg_customers.sql:4: cust_id,"],
    )
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[asset], deepest_hop=1)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=None)

    narrative = narrative_result.narratives[0]
    assert narrative.source == "template"
    assert "stg_customers" in narrative.narrative_text
    assert "cust_id" in narrative.narrative_text
    assert "models/staging/stg_customers.sql:4: cust_id," in narrative.narrative_text


def test_template_narrative_states_origin_vs_cascade_distinctly(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    origin = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, evidence=["a.sql:1: cust_id"])
    cascade = _asset(name="dim_customers", compile_status=CASCADE_HARD_BREAK, hop=2)
    result = AssessmentResult(
        changed_urn="urn:root", changed_column="cust_id", scanned=[origin, cascade], deepest_hop=2
    )

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=None)
    by_name = {n.name: n.narrative_text for n in narrative_result.narratives}

    assert "directly references the changed column" in by_name["stg_customers"]
    assert "upstream dependency" in by_name["dim_customers"]


def test_template_narrative_flags_silent_patch_risk_on_hard_break_with_select_star(monkeypatch):
    # This is the fct_revenue case from the real estate and spec §3's own
    # example: a hard break today (compile_status is CASCADE_HARD_BREAK, so
    # break_mode is HARD_BREAK) that *also* carries a SELECT * -- a wrong fix
    # would turn today's loud failure into tomorrow's silent corruption.
    _clear_all_provider_keys(monkeypatch)
    fct_revenue = _asset(
        name="fct_revenue",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=True,
        evidence=["models/marts/fct_revenue.sql:12: c.*"],
        hop=2,
        usage_count=12,
        is_dashboard_exposed=True,
    )
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[fct_revenue], deepest_hop=2)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=None)
    text = narrative_result.narratives[0].narrative_text

    assert fct_revenue.break_mode == "HARD_BREAK"  # sanity: compile_status wins the property
    assert "loud" in text
    assert "silently" in text
    assert "SELECT *" in text
    assert "models/marts/fct_revenue.sql:12: c.*" in text


def test_template_narrative_does_not_invent_facts_when_none_present(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    bare = _asset(
        name="bare_model",
        compile_status=ORIGIN_HARD_BREAK,
        evidence=[],
        usage_count=0,
        is_dashboard_exposed=False,
        owners=[],
    )
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[bare], deepest_hop=1)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=None)
    text = narrative_result.narratives[0].narrative_text

    assert "Evidence:" not in text  # no evidence on record -- nothing to cite
    assert "dashboard" not in text.lower()
    assert "queries" not in text.lower() and "query" not in text.lower()


def test_template_narrative_mentions_dashboard_and_usage_when_present(monkeypatch):
    _clear_all_provider_keys(monkeypatch)
    exposed = _asset(
        name="fct_revenue",
        compile_status=CASCADE_HARD_BREAK,
        usage_count=12,
        is_dashboard_exposed=True,
    )
    result = AssessmentResult(changed_urn="urn:root", changed_column="cust_id", scanned=[exposed], deepest_hop=2)

    narrative_result = build_narratives(result, changed_table="raw_customers", llm_client=None)
    text = narrative_result.narratives[0].narrative_text

    assert "dashboard" in text.lower()
    assert "12" in text
