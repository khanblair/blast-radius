from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, ORIGIN_HARD_BREAK, AssessmentResult, AssetAssessment
from agent.decision.engine import (
    CHANGE_ADD_COLUMN,
    CHANGE_DROP_COLUMN,
    CHANGE_RENAME,
    CHANGE_WIDEN_TYPE,
    DEFER_DEEPEST_HOP_THRESHOLD,
    DEFER_HARD_BREAK_THRESHOLD,
    decide_migration,
)
from agent.decision.models import ADDITIVE, BREAKING, NO_MIGRATION_NEEDED


def _asset(**overrides):
    defaults = {
        "urn": "urn:li:dataset:x",
        "name": "x",
        "compile_status": ORIGIN_HARD_BREAK,
        "select_star_exposure": False,
        "hop": 1,
        "usage_count": 0,
        "is_dashboard_exposed": False,
        "has_business_owner": False,
    }
    defaults.update(overrides)
    return AssetAssessment(**defaults)


def _result(assets, **overrides):
    defaults = {"changed_urn": "urn:li:dataset:root", "changed_column": "cust_id"}
    defaults.update(overrides)
    return AssessmentResult(scanned=assets, **defaults)


# --- NO_MIGRATION_NEEDED -----------------------------------------------------


def test_no_migration_needed_when_nothing_affected():
    unaffected = _asset(compile_status=NOT_IMPACTED, select_star_exposure=False)
    result = _result([unaffected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == NO_MIGRATION_NEEDED
    assert "0 affected" in decision.rationale or "No downstream asset" in decision.rationale
    assert decision.recommended_strategy is None
    assert decision.options == []
    assert decision.rejected == []


def test_no_migration_needed_wins_over_additive_change_type_when_nothing_affected():
    # Zero downstream references is checked first, unconditionally -- even a
    # nominally additive change type collapses to NO_MIGRATION_NEEDED when
    # there is truly nothing to weigh options against.
    unaffected = _asset(compile_status=NOT_IMPACTED, select_star_exposure=False)
    result = _result([unaffected])

    decision = decide_migration(result, change_type=CHANGE_ADD_COLUMN)

    assert decision.decision_type == NO_MIGRATION_NEEDED


def test_no_migration_needed_with_empty_scanned_list():
    result = _result([])
    decision = decide_migration(result, change_type=CHANGE_RENAME)
    assert decision.decision_type == NO_MIGRATION_NEEDED


# --- ADDITIVE ----------------------------------------------------------------


def test_additive_for_add_column_when_downstream_references_exist():
    # Fabricated: a widened/added column that existing consumers already
    # reference (e.g. a widened type read by a mart) -- affected is
    # non-empty, so this actually exercises the ADDITIVE branch rather than
    # silently falling through NO_MIGRATION_NEEDED.
    affected = _asset(compile_status=ORIGIN_HARD_BREAK)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_ADD_COLUMN)

    assert decision.decision_type == ADDITIVE
    assert decision.recommended_strategy is None
    assert decision.options == []
    assert decision.rejected == []
    assert "add_column" in decision.rationale


def test_additive_for_widen_type_when_downstream_references_exist():
    affected = _asset(compile_status=CASCADE_HARD_BREAK)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_WIDEN_TYPE)

    assert decision.decision_type == ADDITIVE
    assert "widen_type" in decision.rationale


def test_rename_never_produces_additive():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == BREAKING


def test_drop_column_never_produces_additive():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_DROP_COLUMN)

    assert decision.decision_type == BREAKING


# --- BREAKING: strategy A (direct patch) -------------------------------------


def test_breaking_recommends_direct_patch_for_small_non_exposed_blast_radius():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == BREAKING
    assert decision.recommended_strategy == "A"
    rejected_ids = {r.strategy_id for r in decision.rejected}
    assert rejected_ids == {"B", "C"}
    assert len(decision.options) == 3


def test_breaking_direct_patch_rejection_reasons_reference_context():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    reasons = {r.strategy_id: r.reason for r in decision.rejected}
    assert "dashboard" in reasons["B"].lower()
    assert "defer" in reasons["C"].lower() or "small enough" in reasons["C"].lower()


# --- BREAKING: strategy B (bridge) -------------------------------------------


def test_breaking_recommends_bridge_when_any_affected_asset_is_dashboard_exposed():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK, hop=2, is_dashboard_exposed=True)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == BREAKING
    assert decision.recommended_strategy == "B"
    rejected_ids = {r.strategy_id for r in decision.rejected}
    assert rejected_ids == {"A", "C"}


def test_breaking_bridge_recommendation_names_the_exposed_asset():
    affected = _asset(name="fct_revenue", compile_status=ORIGIN_HARD_BREAK, hop=2, is_dashboard_exposed=True)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert "fct_revenue" in decision.rationale


def test_breaking_bridge_wins_even_with_some_non_exposed_affected_assets():
    exposed = _asset(name="fct_revenue", urn="urn:1", compile_status=ORIGIN_HARD_BREAK, hop=2, is_dashboard_exposed=True)
    quiet = _asset(name="stg_customers", urn="urn:2", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False)
    result = _result([exposed, quiet])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "B"


# --- BREAKING: strategy C (defer & deprecate) --------------------------------


def test_breaking_recommends_defer_when_hard_break_count_exceeds_threshold():
    # DEFER_HARD_BREAK_THRESHOLD hard breaks is still within bounds ("more
    # than", not "at least") -- one more crosses it. None are dashboard
    # exposed, isolating the hard-break-count trigger from the exposure one.
    assets = [
        _asset(urn=f"urn:{i}", name=f"asset_{i}", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False)
        for i in range(DEFER_HARD_BREAK_THRESHOLD + 1)
    ]
    result = _result(assets)

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == BREAKING
    assert decision.recommended_strategy == "C"
    rejected_ids = {r.strategy_id for r in decision.rejected}
    assert rejected_ids == {"A", "B"}


def test_breaking_does_not_recommend_defer_at_exactly_the_threshold():
    # Exactly at the threshold must NOT trigger defer -- confirms the ">"
    # (strict) semantics rather than ">=".
    assets = [
        _asset(urn=f"urn:{i}", name=f"asset_{i}", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False)
        for i in range(DEFER_HARD_BREAK_THRESHOLD)
    ]
    result = _result(assets)

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "A"


def test_breaking_recommends_defer_when_deepest_affected_hop_reaches_threshold():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK, hop=DEFER_DEEPEST_HOP_THRESHOLD, is_dashboard_exposed=False)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "C"


def test_breaking_does_not_recommend_defer_just_below_hop_threshold():
    affected = _asset(compile_status=ORIGIN_HARD_BREAK, hop=DEFER_DEEPEST_HOP_THRESHOLD - 1, is_dashboard_exposed=False)
    result = _result([affected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "A"


def test_breaking_defer_takes_precedence_over_dashboard_exposure():
    # Both the defer condition and the exposure condition hold -- defer
    # (the bigger risk signal) must win over bridge.
    assets = [
        _asset(urn=f"urn:{i}", name=f"asset_{i}", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=True)
        for i in range(DEFER_HARD_BREAK_THRESHOLD + 1)
    ]
    result = _result(assets)

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "C"


def test_defer_rationale_is_not_self_contradictory_with_zero_hard_breaks():
    # Regression coverage for a confirmed bug: the hop-depth defer condition
    # can trip on its own with hard_break_count at 0 (an all-SILENT_CORRUPTION
    # chain -- NOT_IMPACTED + select_star_exposure), and the old rationale
    # text unconditionally said "0 hard break(s) ... exceed the bar for a
    # same-day fix (> 5 hard breaks ...)", which is a false/self-contradictory
    # claim (0 does not exceed 5). The text must not cite the hard-break
    # count as the trigger when it wasn't.
    silent_corruption_only = _asset(
        compile_status=NOT_IMPACTED,
        select_star_exposure=True,
        hop=DEFER_DEEPEST_HOP_THRESHOLD,
    )
    result = _result([silent_corruption_only])
    assert result.hard_break_count == 0  # sanity check on the fabricated scenario

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "C"
    assert "0 hard break(s) exceed" not in decision.rationale
    for rejection in decision.rejected:
        assert "touching all 0 hard breaks" not in rejection.reason


def test_unaffected_deep_asset_does_not_inflate_defer_signal():
    # A deep but UNAFFECTED asset must not push the deepest-affected-hop
    # signal past the defer threshold -- only affected assets count.
    shallow_affected = _asset(
        urn="urn:1", name="affected", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=False
    )
    deep_unaffected = _asset(
        urn="urn:2",
        name="unaffected",
        compile_status=NOT_IMPACTED,
        select_star_exposure=False,
        hop=DEFER_DEEPEST_HOP_THRESHOLD + 5,
        is_dashboard_exposed=False,
    )
    result = _result([shallow_affected, deep_unaffected])

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.recommended_strategy == "A"


# --- Canonical demo scenario --------------------------------------------------


def test_canonical_scenario_recommends_bridge():
    # Mirrors the live raw_customers.cust_id rename: 3 hard breaks, deepest
    # affected hop 2, fct_revenue dashboard-exposed. Well below both defer
    # thresholds, so this must fall out of the exposure rule, not be forced.
    stg = _asset(urn="urn:1", name="stg_customers", compile_status=ORIGIN_HARD_BREAK, hop=1, is_dashboard_exposed=True)
    dim = _asset(urn="urn:2", name="dim_customers", compile_status=CASCADE_HARD_BREAK, hop=2, is_dashboard_exposed=True)
    fct_revenue = _asset(
        urn="urn:3", name="fct_revenue", compile_status=CASCADE_HARD_BREAK, hop=2, is_dashboard_exposed=True, usage_count=12
    )
    fct_orders = _asset(
        urn="urn:4", name="fct_orders", compile_status=NOT_IMPACTED, select_star_exposure=False, hop=2, is_dashboard_exposed=True
    )
    result = _result([stg, dim, fct_revenue, fct_orders], deepest_hop=2)

    decision = decide_migration(result, change_type=CHANGE_RENAME)

    assert decision.decision_type == BREAKING
    assert decision.recommended_strategy == "B"
    assert {r.strategy_id for r in decision.rejected} == {"A", "C"}
