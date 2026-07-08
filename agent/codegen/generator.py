"""Codegen (Phase 5 Part A): template-anchored patch generation for an
ORIGIN_HARD_BREAK asset (e.g. spec's canonical demo scenario --
stg_customers.sql reading raw_customers.cust_id, which is renamed to
customer_id -- but not limited to that one file; see below).

Template-anchored generation: the model (or, with no key configured, a
deterministic fallback) is asked to produce only one constrained slot -- the
exact text of the column-selection line that must change to read the renamed
source column while re-aliasing the output back to the original column name
-- and that slot is spliced into the CALLER-SUPPLIED `file_content` at the
exact line that referenced the old column, leaving every other line
byte-for-byte unchanged (`_replace_column_line`).

This is the safety property of "template-anchored": no matter what the model
does or hallucinates, only that one line's text can end up in the rendered
file. Earlier this was implemented by rendering a *static* Jinja skeleton
file that hardcoded stg_customers.sql's exact structure (header comment,
other column names, source table) -- which meant patching any OTHER origin
file silently produced stg_customers-shaped content instead of that file's
actual structure (syntactically valid SQL, so V1/V2 verification couldn't
catch it -- caught by hand while building Phase 9's examples, see
tests/test_codegen_generator.py's generalization tests). Splicing into the
real `file_content` fixes this: the "skeleton" is now whatever file is
actually being patched, not a fixed example of one.

Mirrors agent/narrative/builder.py's discipline: a SYSTEM_PROMPT constrains
the model to rephrase/transform given facts only, and `LLMNotConfigured`
(raised by agent.narrative.llm_client.build_llm_client when no provider key
is set) is caught and routed to a deterministic template fallback -- required
for the demo today (no key configured) and for tests to run without live API
access, so it is a first-class path, not an afterthought.
"""
from __future__ import annotations

import re

from agent.narrative.llm_client import LLMClient, LLMNotConfigured, build_llm_client

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


def _normalize_line_style(core_text: str, current_line: str) -> str:
    """Reapplies `current_line`'s exact indentation and trailing-comma style
    to `core_text` -- indentation and comma placement are structural facts
    about the file being patched, not something to trust an LLM's raw text
    formatting for. A live run against a real provider (DeepSeek) proved
    this the hard way: the system prompt explicitly asks the model to
    preserve the original indentation, and on one call it did -- on another,
    functionally identical call, it silently dropped the leading whitespace
    (still valid SQL, since whitespace is insignificant there, but a
    formatting regression a human reviewer would notice). Both the LLM path
    and the deterministic template path now go through this single
    normalizer instead of each independently trying to get formatting
    right, so this can never regress for either path again.

    `core_text` must be non-empty (trimmed) -- callers must check for an
    empty/garbage LLM response and fall back to the template *before*
    calling this, since normalizing an empty string would silently produce
    a syntactically-plausible-looking but empty `"    ,"` line."""
    core_text = core_text.strip()
    if not core_text:
        raise ValueError("core_text must be non-empty -- caller should have fallen back to the template")
    if core_text.endswith(","):
        core_text = core_text[:-1].rstrip()
    indent = current_line[: len(current_line) - len(current_line.lstrip())]
    trailing_comma = "," if current_line.rstrip().endswith(",") else ""
    return f"{indent}{core_text}{trailing_comma}"


def _template_column_line(old_column: str, new_column: str, current_line: str) -> str:
    """Deterministic fallback: textually substitutes the source read while
    re-aliasing the output back to `old_column`, in `current_line`'s style."""
    return _normalize_line_style(f"{new_column} as {old_column}", current_line)


def _clean_llm_output(text: str) -> str:
    """Strips surrounding whitespace and defensively removes markdown code
    fences, in case the model wraps its one-line answer in ```sql ... ```
    despite the system prompt's instruction not to. Returns the "core" text
    only -- callers must reapply the correct indentation/comma style via
    `_normalize_line_style` rather than trusting this output's whitespace,
    since a live LLM has been observed to drop leading indentation on some
    calls and preserve it on others for the identical request."""
    text = text.strip()
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


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


def _replace_column_line(file_content: str, old_line: str, new_column_line: str) -> str:
    """Splices `new_column_line` into `file_content` in place of `old_line`
    (the exact line `_extract_column_line` identified as the one referencing
    `old_column`), leaving every other line byte-for-byte unchanged -- this
    is what makes the transformation "template-anchored" to whatever file is
    actually being patched, not to a fixed example file. Preserves each
    line's original trailing-newline style."""
    lines = file_content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == old_line:
            newline = "\n" if line.endswith("\n") else ""
            lines[i] = new_column_line.rstrip("\n") + newline
            return "".join(lines)
    raise ValueError(f"could not locate the line to replace in file_content: {old_line!r}")


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
    both to locate the existing column-selection line (for LLM context and
    for the template fallback's indentation/comma style) AND as the base
    the new line is spliced into (`_replace_column_line`), so the returned
    content is `file_content` with only that one line changed, regardless of
    which file this is or what the LLM does.

    Raises `ValueError` if `old_column` isn't found on any non-comment line
    of `file_content` -- there is no line to safely anchor the replacement
    to, and silently returning unmodified (or worse, unrelated) content
    would be a correctness bug, not a graceful fallback.

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
    if current_line is None:
        raise ValueError(
            f"column `{old_column}` not found on any non-comment line of the given file_content -- "
            "nothing to anchor the patch to"
        )

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
            core_text = _clean_llm_output(raw)
            # Empty/garbage LLM output must fall through to the template
            # below -- normalizing an empty core_text would otherwise
            # silently produce a malformed line (see _normalize_line_style).
            column_line = _normalize_line_style(core_text, current_line) if core_text else None
        except Exception:
            # A runtime failure (rate limit, network, transient API error)
            # shouldn't block codegen -- fall back to the template just like
            # the no-key path does.
            column_line = None

    if not column_line:
        column_line = _template_column_line(old_column, new_column, current_line)

    return _replace_column_line(file_content, current_line, column_line)
