"""Generates this example's dossier-output.txt.

SYNTHETIC INPUT, REAL CODE: this project's actual demo estate is
deliberately small ("small but deep -- one killer change exercises
everything"), so it never naturally trips the Decision Engine's
Strategy-C (defer) thresholds (DEFER_HARD_BREAK_THRESHOLD=5 hard breaks,
or DEFER_DEEPEST_HOP_THRESHOLD=4 affected-hop depth -- see
agent/decision/engine.py). To show that branch of the judgment spectrum
honestly, this script fabricates an AssessmentResult shaped like a much
larger organization's lineage graph (7 hard breaks spanning hop 1-4) and
runs it through the REAL, unmodified decide_migration / build_narratives /
render_dossier functions -- nothing about the decision logic or rendering
is faked, only the input data. Re-run with:

    python examples/large-blast-defer/generate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.assessment.models import AssessmentResult, AssetAssessment, ORIGIN_HARD_BREAK, CASCADE_HARD_BREAK
from agent.decision.engine import decide_migration
from agent.decision.gate import confirm_decision, render_decision
from agent.dossier.renderer import render_dossier
from agent.narrative.builder import build_narratives

CHANGED_URN = "urn:li:dataset:(urn:li:dataPlatform:postgres,warehouse.public.customer_master,PROD)"
CHANGED_COLUMN = "customer_id"

# A fabricated org-scale lineage graph: one origin hard break, six cascades
# fanning out across four hops, two of them dashboard-exposed. This is the
# shape that should make the Decision Engine reach for Strategy C.
SCANNED = [
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.staging.stg_customer_master,PROD)",
        name="stg_customer_master",
        compile_status=ORIGIN_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/staging/stg_customer_master.sql:6: customer_id,"],
        hop=1,
        usage_count=40,
        is_dashboard_exposed=False,
        owners=["urn:li:corpuser:data-platform-team"],
        has_business_owner=False,
        dbt_file_path="models/staging/stg_customer_master.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.core.dim_customer,PROD)",
        name="dim_customer",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/core/dim_customer.sql: does not read public.customer_master directly -- fails only because an upstream dependency does"],
        hop=2,
        usage_count=88,
        is_dashboard_exposed=False,
        owners=["urn:li:corpuser:data-platform-team"],
        has_business_owner=True,
        dbt_file_path="models/core/dim_customer.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.finance.fct_billing,PROD)",
        name="fct_billing",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/finance/fct_billing.sql: does not read public.customer_master directly -- fails only because an upstream dependency does"],
        hop=3,
        usage_count=210,
        is_dashboard_exposed=True,
        owners=["urn:li:corpuser:finance-eng"],
        has_business_owner=True,
        dbt_file_path="models/finance/fct_billing.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.finance.fct_revenue_recognition,PROD)",
        name="fct_revenue_recognition",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=True,
        evidence=["models/finance/fct_revenue_recognition.sql: does not read public.customer_master directly -- fails only because an upstream dependency does",
                   "models/finance/fct_revenue_recognition.sql:19: b.*"],
        hop=4,
        usage_count=340,
        is_dashboard_exposed=True,
        owners=["urn:li:corpuser:finance-eng"],
        has_business_owner=True,
        dbt_file_path="models/finance/fct_revenue_recognition.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.marketing.dim_customer_segment,PROD)",
        name="dim_customer_segment",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/marketing/dim_customer_segment.sql: does not read public.customer_master directly -- fails only because an upstream dependency does"],
        hop=3,
        usage_count=52,
        is_dashboard_exposed=False,
        owners=["urn:li:corpuser:marketing-analytics"],
        has_business_owner=True,
        dbt_file_path="models/marketing/dim_customer_segment.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.marketing.fct_campaign_attribution,PROD)",
        name="fct_campaign_attribution",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/marketing/fct_campaign_attribution.sql: does not read public.customer_master directly -- fails only because an upstream dependency does"],
        hop=4,
        usage_count=61,
        is_dashboard_exposed=False,
        owners=["urn:li:corpuser:marketing-analytics"],
        has_business_owner=False,
        dbt_file_path="models/marketing/fct_campaign_attribution.sql",
    ),
    AssetAssessment(
        urn="urn:li:dataset:(urn:li:dataPlatform:dbt,warehouse.support.fct_ticket_customer,PROD)",
        name="fct_ticket_customer",
        compile_status=CASCADE_HARD_BREAK,
        select_star_exposure=False,
        evidence=["models/support/fct_ticket_customer.sql: does not read public.customer_master directly -- fails only because an upstream dependency does"],
        hop=2,
        usage_count=19,
        is_dashboard_exposed=False,
        owners=["urn:li:corpuser:support-eng"],
        has_business_owner=False,
        dbt_file_path="models/support/fct_ticket_customer.sql",
    ),
]


def main() -> None:
    assessment = AssessmentResult(
        changed_urn=CHANGED_URN,
        changed_column=CHANGED_COLUMN,
        scanned=SCANNED,
        deepest_hop=4,
        mcp_call_trace=[],
    )

    narrative = build_narratives(assessment, changed_table="customer_master")
    decision = decide_migration(assessment, change_type="rename")
    confirm_decision(decision, auto_approve=True)

    dossier = render_dossier(
        assessment=assessment,
        narrative=narrative,
        decision=decision,
        self_correction=None,  # Strategy C defers the fix entirely -- no codegen runs
        original_content=None,
    )

    out_path = Path(__file__).resolve().parent / "dossier-output.txt"
    out_path.write_text(dossier + "\n")
    print(f"Wrote {out_path}")
    print()
    print(render_decision(decision))


if __name__ == "__main__":
    main()
