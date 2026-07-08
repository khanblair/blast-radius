from agent.assessment.models import NOT_IMPACTED, ORIGIN_HARD_BREAK, AssetAssessment
from agent.assessment.severity import rank, score


def _asset(**overrides):
    defaults = dict(
        urn="urn:li:dataset:x",
        name="x",
        compile_status=ORIGIN_HARD_BREAK,
        select_star_exposure=False,
        usage_count=0,
        is_dashboard_exposed=False,
        has_business_owner=False,
    )
    defaults.update(overrides)
    return AssetAssessment(**defaults)


def test_hard_break_scores_higher_than_silent_corruption():
    hard = _asset(compile_status=ORIGIN_HARD_BREAK)
    silent = _asset(compile_status=NOT_IMPACTED, select_star_exposure=True)
    assert score(hard) > score(silent)


def test_unaffected_scores_zero():
    unaffected = _asset(compile_status=NOT_IMPACTED, select_star_exposure=False)
    assert score(unaffected) == 0.0


def test_dashboard_exposure_increases_score():
    base = _asset(is_dashboard_exposed=False)
    exposed = _asset(is_dashboard_exposed=True)
    assert score(exposed) > score(base)


def test_business_owner_increases_score():
    base = _asset(has_business_owner=False)
    business = _asset(has_business_owner=True)
    assert score(business) > score(base)


def test_usage_count_increases_score_monotonically():
    low = _asset(usage_count=1)
    high = _asset(usage_count=100)
    assert score(high) > score(low)


def test_rank_sorts_descending_and_sets_severity_score():
    low = _asset(usage_count=0)
    high = _asset(usage_count=100, is_dashboard_exposed=True, has_business_owner=True)
    ranked = rank([low, high])
    assert ranked[0] is high
    assert ranked[0].severity_score > ranked[1].severity_score
    assert low.severity_score == score(low)
