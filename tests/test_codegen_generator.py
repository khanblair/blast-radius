"""Unit tests for the Codegen generator (agent/codegen/generator.py) against
the real stg_customers.sql content, matching the style of
tests/test_narrative_builder.py / tests/test_narrative_llm_client.py.

These confirm: the deterministic template fallback performs the exact
textual transformation (read the new column, re-alias to the old column
name, everything else byte-for-byte unchanged), the LLM path is used when a
client is given and its output flows into the rendered file, failure
evidence from a prior attempt reaches the LLM's prompt, and the no-LLM-
configured path (mirroring agent/narrative/builder.py's test pattern) falls
back to the template rather than erroring.
"""
from __future__ import annotations

from pathlib import Path

from agent.codegen.generator import SYSTEM_PROMPT, generate_patch
from agent.narrative.llm_client import PROVIDER_API_KEY_ENV, build_llm_client

ORIGINAL_STG_CUSTOMERS = (
    Path(__file__).resolve().parents[1] / "estate" / "dbt_project" / "models" / "staging" / "stg_customers.sql"
).read_text()

ORIGINAL_STG_PAYMENTS = (
    Path(__file__).resolve().parents[1] / "estate" / "dbt_project" / "models" / "staging" / "stg_payments.sql"
).read_text()


def _clear_all_provider_keys(monkeypatch):
    for env_var in PROVIDER_API_KEY_ENV.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


# --- template fallback path (no LLM configured) -----------------------------


def test_template_fallback_used_when_no_llm_client_given(monkeypatch):
    _clear_all_provider_keys(monkeypatch)  # exact demo path: no key configured

    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=None)

    assert "customer_id as cust_id," in patched
    assert "    cust_id,\n" not in patched  # the old bare-select line is gone


def test_template_fallback_preserves_everything_else_byte_for_byte(monkeypatch):
    _clear_all_provider_keys(monkeypatch)

    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=None)

    original_lines = ORIGINAL_STG_CUSTOMERS.splitlines()
    patched_lines = patched.splitlines()

    assert len(original_lines) == len(patched_lines)
    for original_line, patched_line in zip(original_lines, patched_lines):
        if "cust_id," in original_line and "select" not in original_line and not original_line.strip().startswith("--"):
            continue  # this is the one slot allowed to change
        assert original_line == patched_line


def test_template_fallback_does_not_mistake_header_comment_for_the_select_line(monkeypatch):
    # stg_customers.sql's header comment mentions "cust_id" in prose -- the
    # extraction logic must skip comment lines so it patches the actual
    # SELECT line, not the comment.
    _clear_all_provider_keys(monkeypatch)

    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=None)

    assert "-- Explicit cust_id reference" in patched  # header comment untouched
    assert "select\n    customer_id as cust_id,\n" in patched


def test_generate_patch_raises_nothing_when_provider_has_no_key(monkeypatch):
    # Mirrors agent/narrative/builder.py's no-key test: generate_patch(...)
    # with llm_client=None must not raise LLMNotConfigured -- it must catch
    # it internally and fall back.
    _clear_all_provider_keys(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=None)

    assert "customer_id as cust_id" in patched


# --- LLM path (fake client / canned response) -------------------------------


def test_llm_client_output_flows_into_rendered_file():
    def fake_generate(system, user):
        return "    customer_id as cust_id,"

    client = build_llm_client(provider="anthropic", generate_fn=fake_generate)
    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert "    customer_id as cust_id,\n    first_name," in patched


def test_llm_client_receives_old_new_column_and_file_content():
    captured = []

    def fake_generate(system, user):
        captured.append((system, user))
        return "    customer_id as cust_id,"

    client = build_llm_client(provider="anthropic", generate_fn=fake_generate)
    generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert len(captured) == 1
    system, user = captured[0]
    assert system == SYSTEM_PROMPT
    assert "old_column: cust_id" in user
    assert "new_column: customer_id" in user
    assert ORIGINAL_STG_CUSTOMERS in user


def test_failure_evidence_reaches_the_llm_prompt_on_retry():
    captured = []

    def fake_generate(system, user):
        captured.append(user)
        return "    customer_id as cust_id,"

    client = build_llm_client(provider="anthropic", generate_fn=fake_generate)
    generate_patch(
        "cust_id",
        "customer_id",
        ORIGINAL_STG_CUSTOMERS,
        failure_evidence="column c.customer_id does not exist",
        llm_client=client,
    )

    assert len(captured) == 1
    assert "column c.customer_id does not exist" in captured[0]


def test_llm_output_with_no_leading_indentation_is_normalized_to_match_file_style():
    # Regression coverage for a real bug found via a live DeepSeek call: the
    # exact same request (raw_customers.cust_id -> customer_id) returned
    # correctly-indented output on one call and, on a separate,
    # functionally identical call, silently dropped the leading whitespace
    # -- still valid SQL (whitespace-insignificant), but a formatting
    # regression a human reviewer would notice. Codegen must not trust an
    # LLM's raw whitespace for a structural fact like indentation.
    def unindented_generate(system, user):
        return "customer_id as cust_id"  # no leading spaces, no trailing comma

    client = build_llm_client(provider="anthropic", generate_fn=unindented_generate)
    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert "    customer_id as cust_id,\n    first_name," in patched


def test_llm_output_that_is_only_whitespace_falls_back_to_template():
    # The empty-core guard: normalizing an empty/whitespace-only LLM
    # response must not silently produce a malformed line (e.g. "    ,") --
    # it must fall back to the template instead.
    def blank_generate(system, user):
        return "   \n  "

    client = build_llm_client(provider="anthropic", generate_fn=blank_generate)
    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert "customer_id as cust_id," in patched
    assert ",," not in patched
    for line in patched.splitlines():
        assert line.strip() != ","


def test_llm_output_survives_markdown_fence_wrapping():
    def fenced_generate(system, user):
        return "```sql\n    customer_id as cust_id,\n```"

    client = build_llm_client(provider="anthropic", generate_fn=fenced_generate)
    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert "```" not in patched
    assert "    customer_id as cust_id,\n    first_name," in patched


def test_llm_failure_falls_back_to_template():
    def raising_generate(system, user):
        raise RuntimeError("simulated transient API failure")

    client = build_llm_client(provider="anthropic", generate_fn=raising_generate)
    patched = generate_patch("cust_id", "customer_id", ORIGINAL_STG_CUSTOMERS, llm_client=client)

    assert "customer_id as cust_id," in patched


# --- generalization to a different origin file --------------------------
# Regression coverage for a real bug found while building Phase 9's examples:
# generate_patch used to render a *fixed* Jinja skeleton hardcoded to
# stg_customers.sql's exact structure, so patching any OTHER file silently
# produced stg_customers-shaped content instead of that file's own
# structure. It now splices into the caller-supplied file_content directly,
# so it must work correctly against a completely different file.


def test_template_fallback_generalizes_to_a_different_origin_file(monkeypatch):
    _clear_all_provider_keys(monkeypatch)

    patched = generate_patch("payment_method", "payment_channel", ORIGINAL_STG_PAYMENTS, llm_client=None)

    assert "payment_channel as payment_method," in patched
    assert "payment_id" in patched and "order_id" in patched and "payment_date" in patched
    assert "raw_payments" in patched
    # must NOT bleed in stg_customers.sql's unrelated structure
    assert "raw_customers" not in patched
    assert "first_name" not in patched


def test_template_fallback_preserves_a_different_file_byte_for_byte_except_one_line(monkeypatch):
    _clear_all_provider_keys(monkeypatch)

    patched = generate_patch("payment_method", "payment_channel", ORIGINAL_STG_PAYMENTS, llm_client=None)

    original_lines = ORIGINAL_STG_PAYMENTS.splitlines()
    patched_lines = patched.splitlines()

    assert len(original_lines) == len(patched_lines)
    for original_line, patched_line in zip(original_lines, patched_lines):
        if "payment_method," in original_line and "select" not in original_line:
            continue  # the one slot allowed to change
        assert original_line == patched_line


def test_generate_patch_raises_when_old_column_not_found():
    import pytest

    with pytest.raises(ValueError, match="not found"):
        generate_patch("nonexistent_column", "new_name", ORIGINAL_STG_CUSTOMERS, llm_client=None)
