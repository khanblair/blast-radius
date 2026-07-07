"""Enrichment: owners, glossary terms, descriptions, and sample queries/usage.

Matches the kickoff guide's "enrich the estate" step (§6.5): assigns owners
per layer, adds glossary terms, adds documentation, and registers
representative historical queries so usage-based severity scoring has real
signal instead of defaulting to zero.
"""
from __future__ import annotations

import hashlib

from datahub.emitter.mce_builder import make_schema_field_urn, make_term_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    CalendarIntervalClass,
    DatasetPropertiesClass,
    DatasetUsageStatisticsClass,
    DatasetUserUsageCountsClass,
    EditableSchemaFieldInfoClass,
    EditableSchemaMetadataClass,
    GlossaryTermAssociationClass,
    GlossaryTermInfoClass,
    GlossaryTermsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    QueryLanguageClass,
    QueryPropertiesClass,
    QuerySourceClass,
    QueryStatementClass,
    QuerySubjectClass,
    QuerySubjectsClass,
    TimeWindowSizeClass,
)

from estate.metadata.emit_common import dataset_urn, get_emitter

DATA_ENGINEERING_OWNER = make_user_urn("jchen")
ANALYTICS_OWNER = make_user_urn("asmith")
SYSTEM_ACTOR = "urn:li:corpuser:datahub"

RAW_AND_STAGING_TABLES = [
    "raw_customers",
    "raw_orders",
    "raw_payments",
    "stg_customers",
    "stg_orders",
    "stg_payments",
]
MART_TABLES = ["dim_customers", "fct_orders", "fct_revenue"]

GLOSSARY_TERMS = {
    "CustomerID": ("Customer ID", "Unique identifier for a customer, currently the `cust_id` physical column."),
    "NetRevenue": ("Net Revenue", "Total order amount recognized for a customer, excluding cancelled orders."),
}

SAMPLE_QUERIES = [
    "SELECT customer_key, amount FROM fct_revenue ORDER BY amount DESC LIMIT 10",
    "SELECT customer_key, COUNT(*) FROM fct_revenue GROUP BY customer_key HAVING COUNT(*) > 5",
    "SELECT * FROM fct_orders WHERE status = 'completed'",
    "SELECT customer_key, SUM(amount) FROM fct_revenue GROUP BY customer_key",
    "SELECT o.order_id, o.amount FROM fct_orders o WHERE o.order_date > now() - interval '30 days'",
    "SELECT COUNT(*) FROM fct_orders WHERE status = 'cancelled'",
    "SELECT customer_key, first_name, last_name FROM dim_customers",
    "SELECT AVG(amount) FROM fct_revenue",
    "SELECT customer_key FROM fct_revenue WHERE order_id = (SELECT MIN(order_id) FROM fct_revenue)",
    "SELECT order_id, customer_key, amount FROM fct_orders WHERE amount > 400",
    "SELECT customer_key, amount FROM fct_revenue WHERE amount > (SELECT AVG(amount) FROM fct_revenue)",
    "SELECT status, COUNT(*) FROM fct_orders GROUP BY status",
]


def _audit_stamp() -> AuditStampClass:
    return AuditStampClass(time=0, actor=SYSTEM_ACTOR)


def build_glossary_term_entity_mcps() -> list[MetadataChangeProposalWrapper]:
    mcps = []
    for term_id, (name, definition) in GLOSSARY_TERMS.items():
        info = GlossaryTermInfoClass(name=name, definition=definition, termSource="INTERNAL")
        mcps.append(MetadataChangeProposalWrapper(entityUrn=make_term_urn(term_id), aspect=info))
    return mcps


def build_ownership_mcps() -> list[MetadataChangeProposalWrapper]:
    mcps = []
    for table in RAW_AND_STAGING_TABLES:
        owner = OwnerClass(owner=DATA_ENGINEERING_OWNER, type=OwnershipTypeClass.TECHNICAL_OWNER)
        mcps.append(MetadataChangeProposalWrapper(entityUrn=dataset_urn(table), aspect=OwnershipClass(owners=[owner])))
    for table in MART_TABLES:
        owner = OwnerClass(owner=ANALYTICS_OWNER, type=OwnershipTypeClass.BUSINESS_OWNER)
        mcps.append(MetadataChangeProposalWrapper(entityUrn=dataset_urn(table), aspect=OwnershipClass(owners=[owner])))
    return mcps


def build_glossary_association_mcps() -> list[MetadataChangeProposalWrapper]:
    audit_stamp = _audit_stamp()
    mcps = []

    customer_id_terms = GlossaryTermsClass(
        terms=[GlossaryTermAssociationClass(urn=make_term_urn("CustomerID"))],
        auditStamp=audit_stamp,
    )
    for table in ["raw_customers", "stg_customers"]:
        field_urn = make_schema_field_urn(dataset_urn(table), "cust_id")
        mcps.append(MetadataChangeProposalWrapper(entityUrn=field_urn, aspect=customer_id_terms))
    field_urn = make_schema_field_urn(dataset_urn("dim_customers"), "customer_key")
    mcps.append(MetadataChangeProposalWrapper(entityUrn=field_urn, aspect=customer_id_terms))

    net_revenue_terms = GlossaryTermsClass(
        terms=[GlossaryTermAssociationClass(urn=make_term_urn("NetRevenue"))],
        auditStamp=audit_stamp,
    )
    field_urn = make_schema_field_urn(dataset_urn("fct_revenue"), "amount")
    mcps.append(MetadataChangeProposalWrapper(entityUrn=field_urn, aspect=net_revenue_terms))

    return mcps


def build_description_mcps() -> list[MetadataChangeProposalWrapper]:
    descriptions = {
        "raw_customers": "Raw customer records loaded from the source system. Primary key is `cust_id`.",
        "fct_revenue": "Order-level revenue joined with the full customer dimension via `SELECT *` -- its shape depends entirely on dim_customers.",
    }
    mcps = []
    for table, description in descriptions.items():
        props = DatasetPropertiesClass(description=description)
        mcps.append(MetadataChangeProposalWrapper(entityUrn=dataset_urn(table), aspect=props))

    field_info = EditableSchemaFieldInfoClass(
        fieldPath="cust_id",
        description="Unique customer identifier. Renaming this column is the canonical Blast Radius demo change.",
    )
    esm = EditableSchemaMetadataClass(editableSchemaFieldInfo=[field_info])
    mcps.append(MetadataChangeProposalWrapper(entityUrn=dataset_urn("raw_customers"), aspect=esm))
    return mcps


def _target_table_for_query(statement: str) -> str:
    if "fct_revenue" in statement:
        return "fct_revenue"
    if "dim_customers" in statement:
        return "dim_customers"
    return "fct_orders"


def build_query_mcps() -> list[MetadataChangeProposalWrapper]:
    mcps = []
    audit_stamp = _audit_stamp()
    for statement in SAMPLE_QUERIES:
        query_id = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]
        query_urn = f"urn:li:query:blast-radius-{query_id}"

        props = QueryPropertiesClass(
            statement=QueryStatementClass(value=statement, language=QueryLanguageClass.SQL),
            source=QuerySourceClass.MANUAL,
            created=audit_stamp,
            lastModified=audit_stamp,
        )
        mcps.append(MetadataChangeProposalWrapper(entityUrn=query_urn, aspect=props))

        target_table = _target_table_for_query(statement)
        subjects = QuerySubjectsClass(subjects=[QuerySubjectClass(entity=dataset_urn(target_table))])
        mcps.append(MetadataChangeProposalWrapper(entityUrn=query_urn, aspect=subjects))
    return mcps


def build_usage_statistics_mcps() -> list[MetadataChangeProposalWrapper]:
    mcps = []
    usage_by_table = [("fct_revenue", 37, 4), ("fct_orders", 21, 3), ("dim_customers", 9, 2)]
    for table, total_queries, unique_users in usage_by_table:
        stats = DatasetUsageStatisticsClass(
            timestampMillis=0,
            eventGranularity=TimeWindowSizeClass(unit=CalendarIntervalClass.DAY),
            uniqueUserCount=unique_users,
            totalSqlQueries=total_queries,
            userCounts=[
                DatasetUserUsageCountsClass(user=DATA_ENGINEERING_OWNER, count=total_queries // 2),
                DatasetUserUsageCountsClass(user=ANALYTICS_OWNER, count=total_queries - total_queries // 2),
            ],
        )
        mcps.append(MetadataChangeProposalWrapper(entityUrn=dataset_urn(table), aspect=stats))
    return mcps


def build_all_mcps() -> list[MetadataChangeProposalWrapper]:
    return (
        build_glossary_term_entity_mcps()
        + build_ownership_mcps()
        + build_glossary_association_mcps()
        + build_description_mcps()
        + build_query_mcps()
        + build_usage_statistics_mcps()
    )


def main() -> None:
    emitter = get_emitter()
    mcps = build_all_mcps()
    for mcp in mcps:
        emitter.emit(mcp)
    print(f"Emitted {len(mcps)} enrichment aspects.")


if __name__ == "__main__":
    main()
