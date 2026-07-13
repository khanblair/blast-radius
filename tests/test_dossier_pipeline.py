"""Unit tests for the pure, unit-testable helpers in
agent/dossier/pipeline.py -- find_origin_assets in particular. The rest of
run_full_pipeline is async/MCP-integration-shaped and is proven via live
runs instead (see examples/), matching this project's established testing
split (README's "fabricated-data unit tests except where a stage is
genuinely integration-shaped").
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, ORIGIN_HARD_BREAK, AssessmentResult, AssetAssessment
from agent.dossier import pipeline as dossier_pipeline
from agent.dossier.pipeline import _run_codegen_and_verification, find_origin_assets


def _asset(**overrides):
    defaults = {
        "urn": "urn:li:dataset:x",
        "name": "x",
        "compile_status": ORIGIN_HARD_BREAK,
        "select_star_exposure": False,
        "dbt_file_path": "models/staging/stg_x.sql",
    }
    defaults.update(overrides)
    return AssetAssessment(**defaults)


def _result(assets):
    return AssessmentResult(changed_urn="urn:li:dataset:root", changed_column="cust_id", scanned=assets)


def test_find_origin_assets_returns_empty_list_when_none_found():
    non_origin = _asset(name="fct_revenue", compile_status=CASCADE_HARD_BREAK)
    unaffected = _asset(name="dim_products", compile_status=NOT_IMPACTED)

    assert find_origin_assets(_result([non_origin, unaffected])) == []


def test_find_origin_assets_excludes_origin_with_no_dbt_file_path():
    # A pure-postgres sibling with no local dbt model has nothing codegen
    # can patch -- must be excluded even though it IS an ORIGIN_HARD_BREAK.
    origin_no_file = _asset(name="raw_customers_sibling", compile_status=ORIGIN_HARD_BREAK, dbt_file_path=None)

    assert find_origin_assets(_result([origin_no_file])) == []


def test_find_origin_assets_returns_single_match():
    origin = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, dbt_file_path="models/staging/stg_customers.sql")

    result = find_origin_assets(_result([origin]))

    assert result == [origin]


def test_find_origin_assets_returns_all_matches_in_scan_order():
    # Regression coverage for the fail-honest fix: a declared change can
    # have more than one true origin (e.g. the same column renamed on two
    # different source tables feeding the same downstream chain) --
    # find_origin_assets must surface all of them, not just the first, so
    # run_full_pipeline can refuse to report a false PASSED for the ones it
    # never patched.
    first_origin = _asset(name="stg_customers", compile_status=ORIGIN_HARD_BREAK, dbt_file_path="models/staging/stg_customers.sql")
    second_origin = _asset(name="stg_other_customers", compile_status=ORIGIN_HARD_BREAK, dbt_file_path="models/staging/stg_other_customers.sql")
    non_origin = _asset(name="fct_revenue", compile_status=CASCADE_HARD_BREAK, dbt_file_path="models/core/fct_revenue.sql")

    result = find_origin_assets(_result([first_origin, non_origin, second_origin]))

    assert result == [first_origin, second_origin]


# --- temp dir cleanup --------------------------------------------------------
# Regression coverage for a confirmed leak: _run_codegen_and_verification
# creates a fresh temp copy of estate/dbt_project via tempfile.mkdtemp() on
# every call and never removed it -- every dossier CLI run permanently
# leaked one temp dbt project copy onto disk.


def test_run_codegen_and_verification_removes_its_temp_dir_on_success(monkeypatch):
    monkeypatch.setattr(dossier_pipeline, "_resolve_llm_client", lambda: None)  # force the fast, deterministic template path

    created_dirs = []
    real_mkdtemp = tempfile.mkdtemp

    def spying_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created_dirs.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", spying_mkdtemp)

    origin = _asset(
        name="stg_customers",
        compile_status=ORIGIN_HARD_BREAK,
        dbt_file_path="models/staging/stg_customers.sql",
    )

    _run_codegen_and_verification(origin, "cust_id", "customer_id", max_attempts=1)

    assert len(created_dirs) == 1
    assert not Path(created_dirs[0]).exists()
