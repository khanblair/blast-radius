"""Assessment Engine: orchestrates Loop 2 traversal, break-mode
classification, and severity scoring into an AssessmentResult (spec §3
Stage 1).
"""
from __future__ import annotations

import uuid

from agent.assessment.break_mode import classify_compile_status, classify_select_star_exposure
from agent.assessment.models import AssessmentResult, AssetAssessment
from agent.assessment.severity import rank
from agent.loops.reasoning_loop import ReasoningLoop
from agent.orchestrator.mcp_client import datahub_mcp_session


def bare_table_name(name: str) -> str:
    """DataHub dataset `name` is 'schema.table' for postgres-platform
    entities and just 'table' for dbt-platform entities -- normalize to the
    bare table name so siblings merge into one logical asset."""
    return name.rsplit(".", 1)[-1]


def dbt_file_path(entity: dict) -> str | None:
    for prop in entity.get("properties", {}).get("customProperties", []) or []:
        if prop.get("key") == "dbt_file_path":
            return prop.get("value")
    return None


def owner_urns_and_business_flag(entity: dict) -> tuple[list[str], bool]:
    owners = entity.get("ownership", {}).get("owners", []) or []
    urns = [o["owner"]["urn"] for o in owners]
    has_business = any(o.get("type") == "BUSINESS_OWNER" for o in owners)
    return urns, has_business


def _platform_of(urn: str) -> str:
    if "dataPlatform:dbt" in urn:
        return "dbt"
    if "dataPlatform:postgres" in urn:
        return "postgres"
    return "other"


def merge_siblings(results: list[dict], by_platform: dict[str, dict[str, dict]], hop_by_name: dict[str, int]) -> None:
    """Groups postgres/dbt sibling entries for the same logical table by
    platform (`by_platform[name] = {"postgres": entity, "dbt": entity}`) --
    kept separate, not collapsed to one "preferred" entity, because Phase 1's
    enrichment (ownership, usage/queries) targets postgres-platform URNs
    while dbt_file_path (needed for break-mode evidence) only exists on
    dbt-platform entities. Collapsing to one would silently lose the other's
    signal."""
    for r in results:
        entity = r["entity"]
        if entity.get("type") != "DATASET":
            continue
        name = bare_table_name(entity.get("name") or "")
        hop_by_name[name] = min(hop_by_name.get(name, r["degree"]), r["degree"])
        by_platform.setdefault(name, {})[_platform_of(entity.get("urn", ""))] = entity


async def assess_change(
    changed_urn: str,
    changed_column: str,
    source_schema: str,
    source_table: str,
    max_hops: int = 3,
    max_tool_calls: int = 30,
) -> AssessmentResult:
    run_id = f"assess-{uuid.uuid4().hex[:8]}"

    async with datahub_mcp_session() as session:
        loop = ReasoningLoop(session=session, run_id=run_id, max_hops=max_hops, max_tool_calls=max_tool_calls)

        column_scoped = await loop.get_lineage(
            changed_urn, rationale=f"scope exact impact of column `{changed_column}`", column=changed_column
        )
        broad = await loop.get_lineage(
            changed_urn, rationale="broader dataset-level reachability, for confirmed-safe reporting and dashboard lookup"
        )

        column_results = column_scoped.get("downstreams", {}).get("searchResults", [])
        broad_results = broad.get("downstreams", {}).get("searchResults", [])

        in_column_scope = {bare_table_name(r["entity"].get("name") or "") for r in column_results if r["entity"].get("type") == "DATASET"}

        by_platform: dict[str, dict[str, dict]] = {}
        hop_by_name: dict[str, int] = {}
        merge_siblings(column_results, by_platform, hop_by_name)
        merge_siblings(broad_results, by_platform, hop_by_name)

        root_name = bare_table_name(source_table)
        by_platform.pop(root_name, None)

        dashboard_urn = next(
            (r["entity"]["urn"] for r in broad_results if r["entity"].get("type") == "DASHBOARD"), None
        )
        dashboard_upstream_names: set[str] = set()
        if dashboard_urn:
            dashboard_upstream = await loop.get_lineage(
                dashboard_urn, rationale="determine which scanned assets actually feed a dashboard (exposure signal)", upstream=True
            )
            dashboard_upstream_names = {
                bare_table_name(r["entity"].get("name") or "")
                for r in dashboard_upstream.get("upstreams", {}).get("searchResults", [])
                if r["entity"].get("type") == "DATASET"
            }

        scanned: list[AssetAssessment] = []
        for name, platforms in by_platform.items():
            dbt_entity = platforms.get("dbt")
            pg_entity = platforms.get("postgres")
            # Ownership/usage were written by Phase 1 enrichment against
            # postgres-platform URNs -- prefer that entity for those signals;
            # dbt_file_path only ever exists on the dbt-platform entity.
            enrichment_entity = pg_entity or dbt_entity or {}
            file_path = dbt_file_path(dbt_entity) if dbt_entity else None

            compile_status, compile_evidence = classify_compile_status(
                name in in_column_scope, file_path, changed_column, source_schema, source_table
            )
            star_exposure, star_evidence = classify_select_star_exposure(file_path)
            owners, has_business_owner = owner_urns_and_business_flag(enrichment_entity)

            usage_urn = enrichment_entity.get("urn")
            usage_data = await loop.get_dataset_queries(
                usage_urn, rationale=f"usage volume for severity scoring of {name}", count=1
            )

            scanned.append(
                AssetAssessment(
                    urn=usage_urn,
                    name=name,
                    compile_status=compile_status,
                    select_star_exposure=star_exposure,
                    evidence=compile_evidence + star_evidence,
                    hop=hop_by_name.get(name),
                    usage_count=usage_data.get("total", 0),
                    is_dashboard_exposed=name in dashboard_upstream_names,
                    owners=owners,
                    has_business_owner=has_business_owner,
                    dbt_file_path=file_path,
                )
            )

        rank(scanned)

        result = AssessmentResult(
            changed_urn=changed_urn,
            changed_column=changed_column,
            scanned=scanned,
            deepest_hop=max(hop_by_name.values(), default=0),
            mcp_call_trace=[entry.__dict__ for entry in loop.trace],
        )
        loop.write_trace()
        return result
