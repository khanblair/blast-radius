from estate.metadata.emit_common import dataset_urn
from estate.metadata.emit_enrichment import (
    GLOSSARY_TERMS,
    MART_TABLES,
    RAW_AND_STAGING_TABLES,
    SAMPLE_QUERIES,
    _target_table_for_query,
    build_all_mcps,
    build_description_mcps,
    build_glossary_association_mcps,
    build_glossary_term_entity_mcps,
    build_ownership_mcps,
    build_query_mcps,
    build_usage_statistics_mcps,
)


def test_build_ownership_covers_every_table_exactly_once():
    mcps = build_ownership_mcps()
    urns = [mcp.entityUrn for mcp in mcps]
    assert len(urns) == len(RAW_AND_STAGING_TABLES) + len(MART_TABLES)
    assert len(urns) == len(set(urns))
    for table in RAW_AND_STAGING_TABLES + MART_TABLES:
        assert dataset_urn(table) in urns


def test_build_glossary_term_entities_match_declared_terms():
    mcps = build_glossary_term_entity_mcps()
    assert len(mcps) == len(GLOSSARY_TERMS)
    for term_id in GLOSSARY_TERMS:
        assert any(mcp.entityUrn == f"urn:li:glossaryTerm:{term_id}" for mcp in mcps)


def test_build_glossary_associations_reference_declared_terms():
    mcps = build_glossary_association_mcps()
    assert len(mcps) > 0
    for mcp in mcps:
        term_urns = [t.urn for t in mcp.aspect.terms]
        assert all(t in (f"urn:li:glossaryTerm:{k}" for k in GLOSSARY_TERMS) for t in term_urns)


def test_build_description_mcps_nonempty():
    mcps = build_description_mcps()
    assert len(mcps) >= 2


def test_target_table_for_query():
    assert _target_table_for_query("SELECT * FROM fct_revenue") == "fct_revenue"
    assert _target_table_for_query("SELECT * FROM dim_customers") == "dim_customers"
    assert _target_table_for_query("SELECT * FROM fct_orders") == "fct_orders"


def test_build_query_mcps_two_per_query():
    mcps = build_query_mcps()
    assert len(mcps) == 2 * len(SAMPLE_QUERIES)


def test_build_usage_statistics_targets_marts():
    mcps = build_usage_statistics_mcps()
    urns = {mcp.entityUrn for mcp in mcps}
    assert dataset_urn("fct_revenue") in urns
    assert dataset_urn("fct_orders") in urns


def test_build_all_mcps_is_the_union_of_builders():
    total = (
        len(build_glossary_term_entity_mcps())
        + len(build_ownership_mcps())
        + len(build_glossary_association_mcps())
        + len(build_description_mcps())
        + len(build_query_mcps())
        + len(build_usage_statistics_mcps())
    )
    assert len(build_all_mcps()) == total
