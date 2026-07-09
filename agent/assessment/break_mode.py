"""Break-mode classification.

Two independent dimensions, not one enum:

- compile_status (ORIGIN_HARD_BREAK / CASCADE_HARD_BREAK / NOT_IMPACTED):
  whether this asset reads the *physical, changed* table directly (origin)
  vs. only fails because an upstream dependency does (cascade). Column-level
  DataHub lineage already tells us which assets are transitively dependent
  on the changed column -- if an asset is in that set, it's origin or
  cascade; if it's only in the broader dataset-level set, it's not impacted.

  Origin is decided structurally (does the compiled query's FROM/JOIN read
  the changed table?), not by textually matching the column name anywhere in
  the file -- a descendant model can re-select a same-named column it
  inherited from an ancestor (e.g. `dim_customers` re-selects `cust_id` from
  `stg_customers`, not from `raw_customers`) without being the origin.

- select_star_exposure: a structural property of an asset's own SQL (does it
  expand an upstream table via unpinned `select *` / `alias.*`), independent
  of whether *this* change currently breaks it. This is what makes an asset
  a SILENT_CORRUPTION risk for *future* fixes, not a symptom of today's break.

Both checks parse dbt's *compiled* SQL (Jinja already resolved to real table
names, under target/compiled/) via sqlglot for structure, then locate
matching lines in the developer-facing *source* .sql file (under models/)
for file:line evidence citations.
"""
from __future__ import annotations

import re
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from agent.assessment.models import CASCADE_HARD_BREAK, NOT_IMPACTED, ORIGIN_HARD_BREAK

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "estate" / "dbt_project"
DBT_PROJECT_NAME = "blast_radius_estate"


def read_source_sql(dbt_file_path: str) -> str:
    """The developer-facing, un-compiled .sql file under models/."""
    return (DBT_PROJECT_DIR / dbt_file_path).read_text()


def read_compiled_sql(dbt_file_path: str) -> str:
    """dbt's Jinja-rendered SQL (real table names, no {{ ref() }}/{{ source() }})."""
    return (DBT_PROJECT_DIR / "target" / "compiled" / DBT_PROJECT_NAME / dbt_file_path).read_text()


def references_physical_table(compiled_sql: str, schema: str, table: str) -> bool:
    parsed = sqlglot.parse_one(compiled_sql, read="postgres")
    return any(
        (t.name or "").lower() == table.lower() and (t.db or "").lower() == schema.lower()
        for t in parsed.find_all(exp.Table)
    )


def find_star_aliases(compiled_sql: str) -> list[str | None]:
    """One entry per star expansion in the query: the qualifying alias (e.g.
    'c' for `c.*`), or None for a bare `*`."""
    parsed = sqlglot.parse_one(compiled_sql, read="postgres")
    aliases = []
    for star in parsed.find_all(exp.Star):
        column = star.parent if isinstance(star.parent, exp.Column) else None
        table_id = column.args.get("table") if column else None
        aliases.append(table_id.name if table_id else None)
    return aliases


def _line_evidence(source_sql: str, pattern: re.Pattern, file_label: str) -> list[str]:
    return [
        f"{file_label}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(source_sql.splitlines(), start=1)
        if not line.strip().startswith("--") and pattern.search(line)
    ]


def classify_compile_status(
    in_column_scope: bool, dbt_file_path: str | None, column: str, source_schema: str, source_table: str
) -> tuple[str, list[str]]:
    """Returns (compile_status, evidence). `source_schema`/`source_table`
    identify the physical table being changed (the root of the declared change)."""
    if not in_column_scope:
        return NOT_IMPACTED, []
    if dbt_file_path is None:
        return CASCADE_HARD_BREAK, ["no local SQL file for this asset -- classified as cascade by column-lineage membership"]

    try:
        compiled_sql = read_compiled_sql(dbt_file_path)
        if references_physical_table(compiled_sql, source_schema, source_table):
            source_sql = read_source_sql(dbt_file_path)
            pattern = re.compile(rf"\b{re.escape(column)}\b", re.IGNORECASE)
            return ORIGIN_HARD_BREAK, _line_evidence(source_sql, pattern, dbt_file_path)

        return (
            CASCADE_HARD_BREAK,
            [f"{dbt_file_path}: does not read {source_schema}.{source_table} directly -- fails only because an upstream dependency does"],
        )
    except (OSError, SqlglotError) as e:
        # A stale/mismatched dbt_file_path (DataHub's customProperties out
        # of sync with what's actually on disk/compiled) or malformed SQL
        # must not crash the whole assessment over one asset -- column-
        # lineage already told us this asset IS affected, so degrade to the
        # same conservative CASCADE_HARD_BREAK the "no local file" branch
        # uses rather than guessing ORIGIN with unverifiable evidence.
        return (
            CASCADE_HARD_BREAK,
            [f"{dbt_file_path}: could not read/parse SQL ({e}) -- classified as cascade, not origin, since this could not be structurally confirmed"],
        )


def classify_select_star_exposure(dbt_file_path: str | None) -> tuple[bool, list[str]]:
    if dbt_file_path is None:
        return False, []
    try:
        aliases = find_star_aliases(read_compiled_sql(dbt_file_path))
    except (OSError, SqlglotError) as e:
        # Same non-crashing degradation as classify_compile_status above --
        # a missing/unparseable compiled file must not take down the whole
        # assessment. Conservatively reports no exposure rather than
        # guessing, but says so explicitly rather than silently claiming
        # "confirmed safe."
        return False, [f"{dbt_file_path}: could not read/parse SQL ({e}) -- select-star exposure could not be checked"]
    if not aliases:
        return False, []

    source_sql = read_source_sql(dbt_file_path)
    evidence = []
    for alias in aliases:
        pattern = re.compile(rf"\b{re.escape(alias)}\.\*") if alias else re.compile(r"select\s+\*")
        evidence.extend(_line_evidence(source_sql, pattern, dbt_file_path))
    return True, evidence
