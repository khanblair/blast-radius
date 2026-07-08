"""Codegen (Phase 5 Part A): template-anchored patch generation for the
ORIGIN_HARD_BREAK asset (spec's canonical demo scenario -- stg_customers.sql
reading raw_customers.cust_id, which is renamed to customer_id).

Template-anchored generation: a Jinja skeleton
(agent/codegen/templates/staging_model_patch.sql.jinja) defines the fixed SQL
structure -- same header comment, same other columns, same source() call as
the real stg_customers.sql -- and the LLM (or, with no key configured, a
deterministic template fallback) fills only one constrained slot: the exact
text of the column-selection line that must change to read the renamed
source column while re-aliasing the output back to the original column name.

This is the safety property of "template-anchored": no matter what the model
does or hallucinates, only that one slot's text can end up in the rendered
file -- the rest of the structure is fixed by the skeleton, byte-for-byte.

Mirrors agent/narrative/builder.py's discipline: a SYSTEM_PROMPT constrains
the model to rephrase/transform given facts only, and `LLMNotConfigured`
(raised by agent.narrative.llm_client.build_llm_client when no provider key
is set) is caught and routed to a deterministic template fallback -- required
for the demo today (no key configured) and for tests to run without live API
access, so it is a first-class path, not an afterthought.
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from agent.narrative.llm_client import LLMClient, LLMNotConfigured, build_llm_client

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SKELETON_TEMPLATE_NAME = "staging_model_patch.sql.jinja"

_JINJA_ENV = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), keep_trailing_newline=True)

SYSTEM_PROMPT = (
    "You are patching exactly one line of a dbt staging model's SQL SELECT "
    "list to absorb an upstream source column rename. You are given the old "
    "and new column names and the model's current full file content, and -- "
    "on a retry -- the exact verification error raised by the previous "
    "attempt.\n\n"
    "Your task: change the single line that currently selects the old "
    "column name from the source so that it instead reads the new column "
    "name, while re-aliasing the output back to the old column name (for "
    "example: `new_column as old_column,`). This keeps every downstream "
    "consumer of this model -- and its schema.yml tests -- completely "
    "unaffected by the rename: only this one line, in this one model, "
    "changes. Preserve the line's original indentation and trailing comma "
    "style.\n\n"
    "If failure evidence from a previous attempt is given, fix specifically "
    "the reported error -- do not regenerate from scratch and do not change "
    "anything unrelated.\n\n"
    "Respond with ONLY the corrected column-selection line: no explanation, "
    "no markdown fences, no surrounding SQL -- just that one line of SQL "
    "text, including a trailing comma if appropriate."
)


def _extract_column_line(file_content: str, old_column: str) -> str | None:
    """Finds the line in the current file content that selects `old_column`
    (e.g. `    cust_id,`) -- the exact slot codegen is allowed to touch.
    Comment lines are skipped (mirrors agent/assessment/break_mode.py's
    `_line_evidence`) so a header comment that merely mentions the column
    name in prose (as stg_customers.sql's does) isn't mistaken for the
    actual SELECT line. Returns None if no non-comment line references it."""
    pattern = re.compile(rf"\b{re.escape(old_column)}\b")
    for line in file_content.splitlines():
        if line.strip().startswith("--"):
            continue
        if pattern.search(line):
            return line
    return None


def _template_column_line(old_column: str, new_column: str, current_line: str | None) -> str:
    """Deterministic fallback: textually substitutes the source read while
    re-aliasing the output back to `old_column`, preserving the current
    line's indentation and trailing comma when available."""
    if current_line is not None:
        indent = current_line[: len(current_line) - len(current_line.lstrip())]
        trailing_comma = "," if current_line.rstrip().endswith(",") else ""
    else:
        indent = "    "
        trailing_comma = ","
    return f"{indent}{new_column} as {old_column}{trailing_comma}"


def _clean_llm_output(text: str) -> str:
    """Strips only surrounding blank lines and defensively removes markdown
    code fences, in case the model wraps its one-line answer in ```sql ...
    ``` despite the system prompt's instruction not to. Deliberately does
    NOT call `.strip()` on the whole blob -- that would also eat the line's
    leading indentation, which the system prompt explicitly asks the model
    to preserve."""
    text = text.strip("\n")
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip("\n")


def _user_prompt(old_column: str, new_column: str, file_content: str, failure_evidence: str | None) -> str:
    lines = [
        f"old_column: {old_column}",
        f"new_column: {new_column}",
        "current file content:",
        file_content,
    ]
    if failure_evidence:
        lines.append("A previous attempt failed verification with this exact error -- fix specifically this:")
        lines.append(failure_evidence)
    else:
        lines.append("This is the first attempt -- no prior failure evidence.")
    return "\n".join(lines)


def _render_skeleton(column_line: str) -> str:
    template = _JINJA_ENV.get_template(SKELETON_TEMPLATE_NAME)
    return template.render(column_line=column_line)


def generate_patch(
    old_column: str,
    new_column: str,
    file_content: str,
    failure_evidence: str | None = None,
    llm_client: LLMClient | None = None,
) -> str:
    """Returns the FULL new file content for the origin staging model,
    patched to read `new_column` from the source while re-aliasing the
    output column back to `old_column` -- so every downstream consumer
    (marts and their schema.yml tests) needs zero changes.

    `file_content` is the CURRENT content of the file being patched -- used
    to locate the existing column-selection line (for LLM context and for
    the template fallback's indentation/comma style). The returned content
    is produced by rendering the fixed Jinja skeleton
    (agent/codegen/templates/staging_model_patch.sql.jinja) with only the
    column-selection line filled in, so the rest of the file's structure is
    guaranteed unchanged regardless of what the LLM does.

    `failure_evidence`, when given, is the raw error from a prior failed
    verification attempt -- passed to the LLM (or ignored by the
    deterministic fallback, which always produces the same correct textual
    transformation) so a retry fixes the reported problem specifically.

    `llm_client`, when given, bypasses provider/key resolution entirely
    (mirrors agent/narrative/builder.py's `llm_client` parameter) -- for
    testability. When not given, one is built from `LLM_PROVIDER`/env; if no
    API key is configured for that provider, `LLMNotConfigured` is caught
    here and generation falls back to the deterministic template -- this is
    the demo's real path today (no key is configured project-wide) and must
    keep working unchanged once a real key is added later.
    """
    current_line = _extract_column_line(file_content, old_column)

    resolved_client = llm_client
    if resolved_client is None:
        try:
            resolved_client = build_llm_client()
        except LLMNotConfigured:
            resolved_client = None

    column_line: str | None = None
    if resolved_client is not None:
        try:
            raw = resolved_client.generate(
                SYSTEM_PROMPT, _user_prompt(old_column, new_column, file_content, failure_evidence)
            )
            column_line = _clean_llm_output(raw)
        except Exception:
            # A runtime failure (rate limit, network, transient API error)
            # shouldn't block codegen -- fall back to the template just like
            # the no-key path does.
            column_line = None

    if not column_line:
        column_line = _template_column_line(old_column, new_column, current_line)

    return _render_skeleton(column_line)
