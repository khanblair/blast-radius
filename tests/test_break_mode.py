from agent.assessment.break_mode import classify_compile_status, classify_select_star_exposure
from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, ORIGIN_HARD_BREAK

SCHEMA = "public"
ROOT_TABLE = "raw_customers"


def test_stg_customers_is_origin_hard_break_for_cust_id():
    # stg_customers.sql reads directly from raw_customers -- the origin.
    status, evidence = classify_compile_status(True, "models/staging/stg_customers.sql", "cust_id", SCHEMA, ROOT_TABLE)
    assert status == ORIGIN_HARD_BREAK
    assert any("cust_id" in e for e in evidence)


def test_evidence_excludes_comment_lines_mentioning_the_column():
    # stg_customers.sql's header comment mentions `cust_id` twice in prose --
    # only the real `select cust_id,` code line should count as evidence.
    _, evidence = classify_compile_status(True, "models/staging/stg_customers.sql", "cust_id", SCHEMA, ROOT_TABLE)
    assert len(evidence) == 1
    assert "-- " not in evidence[0]


def test_dim_customers_is_cascade_hard_break_despite_reusing_column_name():
    # dim_customers.sql reads from stg_customers (not raw_customers) and
    # re-selects `cust_id` as `customer_key` -- textually it mentions cust_id,
    # but structurally it does not read the changed physical table, so it's
    # cascade, not origin.
    status, evidence = classify_compile_status(True, "models/marts/dim_customers.sql", "cust_id", SCHEMA, ROOT_TABLE)
    assert status == CASCADE_HARD_BREAK
    assert evidence


def test_fct_revenue_is_cascade_hard_break_for_cust_id():
    status, _ = classify_compile_status(True, "models/marts/fct_revenue.sql", "cust_id", SCHEMA, ROOT_TABLE)
    assert status == CASCADE_HARD_BREAK


def test_not_in_column_scope_is_not_impacted_regardless_of_file():
    status, evidence = classify_compile_status(False, "models/marts/fct_orders.sql", "cust_id", SCHEMA, ROOT_TABLE)
    assert status == NOT_IMPACTED
    assert evidence == []


def test_missing_dbt_file_path_in_scope_is_cascade():
    status, _ = classify_compile_status(True, None, "cust_id", SCHEMA, ROOT_TABLE)
    assert status == CASCADE_HARD_BREAK


def test_fct_revenue_has_select_star_exposure_on_dim_customers_alias():
    exposed, evidence = classify_select_star_exposure("models/marts/fct_revenue.sql")
    assert exposed is True
    assert any("c.*" in e for e in evidence)


def test_dim_customers_has_no_select_star_exposure():
    exposed, evidence = classify_select_star_exposure("models/marts/dim_customers.sql")
    assert exposed is False
    assert evidence == []


def test_stg_customers_has_no_select_star_exposure():
    exposed, _ = classify_select_star_exposure("models/staging/stg_customers.sql")
    assert exposed is False


# --- stale/missing compiled SQL must degrade, not crash ---------------------
# Regression coverage for a confirmed gap: a dbt_file_path that DataHub says
# exists (via customProperties) but has no matching compiled artifact on
# disk (stale ingestion, renamed model, dbt never compiled for it) used to
# raise FileNotFoundError straight out of classify_compile_status /
# classify_select_star_exposure, crashing the *entire* assessment over one
# asset instead of degrading just that asset's classification.


def test_missing_compiled_sql_degrades_to_cascade_instead_of_crashing():
    status, evidence = classify_compile_status(
        True, "models/staging/does_not_exist.sql", "cust_id", SCHEMA, ROOT_TABLE
    )
    assert status == CASCADE_HARD_BREAK
    assert any("could not read/parse" in e for e in evidence)


def test_missing_compiled_sql_for_star_exposure_degrades_to_false_instead_of_crashing():
    exposed, evidence = classify_select_star_exposure("models/staging/does_not_exist.sql")
    assert exposed is False
    assert any("could not read/parse" in e for e in evidence)
