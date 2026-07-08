from agent.assessment.engine import bare_table_name, dbt_file_path, merge_siblings, owner_urns_and_business_flag


def test_bare_table_name_strips_schema_prefix():
    assert bare_table_name("warehouse.public.fct_revenue") == "fct_revenue"


def test_bare_table_name_passes_through_bare_names():
    assert bare_table_name("fct_revenue") == "fct_revenue"


def test_dbt_file_path_extracts_from_custom_properties():
    entity = {"properties": {"customProperties": [{"key": "dbt_file_path", "value": "models/marts/fct_revenue.sql"}]}}
    assert dbt_file_path(entity) == "models/marts/fct_revenue.sql"


def test_dbt_file_path_returns_none_when_absent():
    assert dbt_file_path({"properties": {"customProperties": []}}) is None
    assert dbt_file_path({}) is None


def test_owner_urns_and_business_flag():
    entity = {
        "ownership": {
            "owners": [
                {"owner": {"urn": "urn:li:corpuser:asmith"}, "type": "BUSINESS_OWNER"},
                {"owner": {"urn": "urn:li:corpuser:jchen"}, "type": "TECHNICAL_OWNER"},
            ]
        }
    }
    urns, has_business = owner_urns_and_business_flag(entity)
    assert urns == ["urn:li:corpuser:asmith", "urn:li:corpuser:jchen"]
    assert has_business is True


def test_owner_urns_and_business_flag_none_business():
    entity = {"ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:jchen"}, "type": "TECHNICAL_OWNER"}]}}
    _, has_business = owner_urns_and_business_flag(entity)
    assert has_business is False


def test_owner_urns_and_business_flag_no_ownership():
    urns, has_business = owner_urns_and_business_flag({})
    assert urns == []
    assert has_business is False


def test_merge_siblings_keeps_postgres_and_dbt_entities_separate():
    # Ownership/usage live on the postgres-platform entity (Phase 1
    # enrichment); dbt_file_path only exists on the dbt-platform entity.
    # Collapsing to one "preferred" entity silently loses the other's data.
    postgres_entity = {
        "type": "DATASET",
        "name": "warehouse.public.fct_revenue",
        "urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.fct_revenue,PROD)",
        "properties": {},
    }
    dbt_entity = {
        "type": "DATASET",
        "name": "fct_revenue",
        "urn": "urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.public.fct_revenue,PROD)",
        "properties": {"customProperties": [{"key": "dbt_file_path", "value": "models/marts/fct_revenue.sql"}]},
    }
    results = [{"entity": postgres_entity, "degree": 2}, {"entity": dbt_entity, "degree": 3}]

    by_platform: dict = {}
    hop_by_name: dict = {}
    merge_siblings(results, by_platform, hop_by_name)

    assert list(by_platform.keys()) == ["fct_revenue"]
    assert by_platform["fct_revenue"]["postgres"]["urn"] == postgres_entity["urn"]
    assert by_platform["fct_revenue"]["dbt"]["urn"] == dbt_entity["urn"]
    assert hop_by_name["fct_revenue"] == 2  # keeps the minimum degree seen


def test_merge_siblings_skips_non_dataset_entities():
    dashboard = {"type": "DASHBOARD", "name": "revenue_dashboard", "urn": "urn:dash"}
    results = [{"entity": dashboard, "degree": 1}]
    by_platform: dict = {}
    hop_by_name: dict = {}
    merge_siblings(results, by_platform, hop_by_name)
    assert by_platform == {}
