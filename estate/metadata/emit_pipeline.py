"""Hand-authored Airflow-style pipeline metadata and the revenue_dashboard entity.

Standing up real Airflow or a real BI tool is out of scope for Week 1
(kickoff guide §6.3) -- this hand-authors the DataFlow/DataJob and Dashboard
entities DataHub would otherwise learn from Airflow/BI-tool ingestion.
"""
from __future__ import annotations

from datahub.api.entities.datajob import DataFlow, DataJob
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import ChangeAuditStampsClass, DashboardInfoClass, EdgeClass
from datahub.metadata.urns import DatasetUrn

from estate.metadata.emit_common import dataset_urn, get_emitter

RAW_TABLES = ["raw_customers", "raw_orders", "raw_payments"]
MART_TABLES = ["dim_customers", "fct_orders", "fct_revenue"]

DASHBOARD_URN = "urn:li:dashboard:(blast_radius,revenue_dashboard)"


def build_pipeline() -> tuple[DataFlow, DataJob]:
    # DataJob.inlets/.outlets require DatasetUrn objects, not plain strings --
    # its own docstring says `List[str]` (a real upstream mismatch, see
    # feedback-notes.md's "Candidate upstream contributions"), but the actual
    # field type is `List[DatasetUrn]`; plain strings pass silently at
    # assignment and only fail later, at .emit() time, with an unhelpful
    # AttributeError. DatasetUrn.from_string(...) here avoids that entirely.
    flow = DataFlow(orchestrator="airflow", id="blast_radius_dbt_pipeline", env="PROD")
    job = DataJob(flow_urn=flow.urn, id="run_dbt_build")
    # NOTE: every raw table -> every mart table, deliberately coarse (this is
    # a single synthetic "run the whole dbt build" job, not per-model tasks).
    # This creates job-level lineage edges broader than dbt's own ref()
    # graph -- e.g. raw_payments -> fct_revenue via this job, even though no
    # dbt model actually connects them. This is the confirmed root cause of
    # the "broad reachability disagrees with the dbt-graph" behavior noted in
    # feedback-notes.md (originally logged as an open, unconfirmed question).
    job.inlets = [DatasetUrn.from_string(dataset_urn(t)) for t in RAW_TABLES]
    job.outlets = [DatasetUrn.from_string(dataset_urn(t)) for t in MART_TABLES]
    return flow, job


def build_dashboard_mcp() -> MetadataChangeProposalWrapper:
    info = DashboardInfoClass(
        title="Revenue Dashboard",
        description="Daily revenue overview, sourced from fct_revenue.",
        lastModified=ChangeAuditStampsClass(),
        datasetEdges=[EdgeClass(destinationUrn=dataset_urn("fct_revenue"))],
    )
    return MetadataChangeProposalWrapper(entityUrn=DASHBOARD_URN, aspect=info)


def main() -> None:
    emitter = get_emitter()
    flow, job = build_pipeline()
    flow.emit(emitter)
    job.emit(emitter)
    emitter.emit(build_dashboard_mcp())
    print(f"Emitted DataFlow {flow.urn}")
    print(f"Emitted DataJob {job.urn}")
    print(f"Emitted Dashboard {DASHBOARD_URN}")


if __name__ == "__main__":
    main()
