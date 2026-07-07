from estate.metadata.emit_common import dataset_urn
from estate.metadata.emit_pipeline import DASHBOARD_URN, MART_TABLES, RAW_TABLES, build_dashboard_mcp, build_pipeline


def test_build_pipeline_flow_and_job_urns():
    flow, job = build_pipeline()
    assert str(flow.urn) == "urn:li:dataFlow:(airflow,blast_radius_dbt_pipeline,PROD)"
    assert str(job.urn) == f"urn:li:dataJob:({flow.urn},run_dbt_build)"


def test_build_pipeline_inlets_outlets():
    _, job = build_pipeline()
    assert {str(u) for u in job.inlets} == {dataset_urn(t) for t in RAW_TABLES}
    assert {str(u) for u in job.outlets} == {dataset_urn(t) for t in MART_TABLES}


def test_build_dashboard_mcp_targets_fct_revenue():
    mcp = build_dashboard_mcp()
    assert mcp.entityUrn == DASHBOARD_URN
    assert mcp.aspect.datasetEdges[0].destinationUrn == dataset_urn("fct_revenue")
