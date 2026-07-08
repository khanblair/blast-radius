# agent/verify/harness.py
"""Verification Harness (spec Stage 5 / Loop 3 -- "Verification Gauntlet").

Runs cheapest-first checks against a candidate dbt model file, stopping at
the first failure so an expensive check never runs on an artifact that
already failed a cheap one. MVP scope is exactly two levels:

V1_STATIC -- sqlglot parse + dialect validation, in-process, no subprocess.
A dbt model file contains Jinja (`{{ ref(...) }}` / `{{ source(...) }}`)
that sqlglot cannot parse directly, so a small regex pre-pass swaps those
for quoted literal identifiers before handing the SQL to
`sqlglot.parse_one(sql, read="postgres")` -- postgres because that's the
estate's warehouse dialect (see agent/assessment/break_mode.py, which
parses the same estate's *compiled* SQL under the same dialect). This is a
cheap pre-filter, not the real gate: it only proves the SQL isn't
syntactically garbage, not that it's valid within the real dbt project.

V2_COMPILE -- the real gate. Runs dbt's own compiler, as a subprocess,
against a real dbt project. This is the only check that can validate
ref()/source() DAG resolution and full Jinja rendering -- exactly what
V1's regex pre-pass can't see (e.g. a ref() to a model that doesn't exist).

parse vs. compile, decided empirically: a model rewritten to read
`{{ ref('does_not_exist_xyz') }}` was run through both `dbt parse` and
`dbt compile --select <model>` against a temp-copied project. Both
surfaced the identical, clear failure --
"Compilation Error\n  Model '...' (models/staging/stg_orders.sql) depends
on a node named 'does_not_exist_xyz' which was not found" -- with a
non-zero exit code, because dbt builds/validates the full dependency graph
during manifest parsing for either command. We chose `dbt compile
--select <model_name>` over `dbt parse` because compile is the closer
match to "run dbt's own compiler against the candidate": it additionally
renders and writes the actual compiled SQL for the target model under
target/compiled/ (the artifact this harness exists to validate), whereas
`dbt parse` only builds the manifest and never touches the model's
rendered SQL at all.

CRITICAL SAFETY NOTE: dbt-core treats DBT_PROJECT_DIR as a real env-var
override for project-dir resolution, and it wins over plain `cwd`-based
detection when no --project-dir flag is given. This repo's own .env sets
DBT_PROJECT_DIR to the real estate/dbt_project -- confirmed empirically
during development: `cd <temp copy> && dbt parse` (no explicit flag, this
var set in the environment) silently ran against the real estate and
rewrote its target/ artifacts, because dbt resolved project-dir from the
env var instead of cwd. The primary defense is that `_invoke_dbt_compile`
*always* passes `--project-dir`/`--profiles-dir` explicitly -- an explicit
CLI flag beats the env var (confirmed empirically the same way: with the
flag passed, the same leaked env var pointed at a decoy directory was
ignored and dbt correctly used the passed-in project_dir). `_dbt_subprocess_env`
also strips DBT_PROJECT_DIR from the subprocess environment as
defense-in-depth, in case a future change to this module ever invokes dbt
without the explicit flag.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import sqlglot
from sqlglot import errors as sqlglot_errors

from agent.verify.models import V1_STATIC, V2_COMPILE, VerificationOutcome, VerificationReport

DBT_DIALECT = "postgres"
DEFAULT_LEVELS = [V1_STATIC, V2_COMPILE]

_REF_PATTERN = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_SOURCE_PATTERN = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")


def _resolve_minimal_jinja(sql: str) -> str:
    """Best-effort Jinja->SQL substitution so sqlglot -- which knows nothing
    about dbt's Jinja -- can parse a dbt model file. Only handles the two
    constructs dbt models actually use: `{{ ref('x') }}` -> `"x"` and
    `{{ source('a', 'b') }}` -> `"a"."b"`. Anything fancier (macros, config
    blocks, control flow) is out of scope for this cheap pre-filter --
    V2_COMPILE is the real gate for those."""
    sql = _SOURCE_PATTERN.sub(lambda m: f'"{m.group(1)}"."{m.group(2)}"', sql)
    sql = _REF_PATTERN.sub(lambda m: f'"{m.group(1)}"', sql)
    return sql


def _read_candidate(project_dir: str, dbt_file_path: str) -> str:
    return (Path(project_dir) / dbt_file_path).read_text()


def _model_name_from_path(dbt_file_path: str) -> str:
    return Path(dbt_file_path).stem


def _run_v1_static(project_dir: str, dbt_file_path: str) -> VerificationOutcome:
    raw_sql = _read_candidate(project_dir, dbt_file_path)
    resolved_sql = _resolve_minimal_jinja(raw_sql)
    try:
        sqlglot.parse_one(resolved_sql, read=DBT_DIALECT)
    except sqlglot_errors.ParseError as exc:
        return VerificationOutcome(
            level=V1_STATIC,
            passed=False,
            message=f"{dbt_file_path} is not valid {DBT_DIALECT} SQL",
            raw_error=str(exc),
        )
    return VerificationOutcome(
        level=V1_STATIC,
        passed=True,
        message=f"{dbt_file_path} parses as valid {DBT_DIALECT} SQL",
    )


def _dbt_subprocess_env(project_dir: str) -> dict:
    """Defense-in-depth for the CRITICAL SAFETY NOTE in the module
    docstring: the real fix is that _invoke_dbt_compile always passes
    --project-dir/--profiles-dir explicitly (an explicit flag beats the
    env var), but strip DBT_PROJECT_DIR here too in case a future caller
    of this function ever drops those flags."""
    env = os.environ.copy()
    env.pop("DBT_PROJECT_DIR", None)
    env["DBT_PROFILES_DIR"] = project_dir
    return env


def _invoke_dbt_compile(project_dir: str, model_name: str) -> subprocess.CompletedProcess:
    """Isolated as its own function so tests can spy on/count dbt
    invocations (e.g. to prove V2 never runs after a V1 failure) without
    actually shelling out."""
    cmd = [
        "dbt", "compile",
        "--select", model_name,
        "--project-dir", project_dir,
        "--profiles-dir", project_dir,
        "--no-use-colors",
    ]
    return subprocess.run(
        cmd,
        cwd=project_dir,
        env=_dbt_subprocess_env(project_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_v2_compile(project_dir: str, dbt_file_path: str) -> VerificationOutcome:
    model_name = _model_name_from_path(dbt_file_path)
    result = _invoke_dbt_compile(project_dir, model_name)
    combined_output = f"{result.stdout or ''}{result.stderr or ''}".strip()
    if result.returncode != 0:
        return VerificationOutcome(
            level=V2_COMPILE,
            passed=False,
            message=f"dbt compile failed for model '{model_name}'",
            raw_error=combined_output or f"dbt compile exited {result.returncode} with no captured output",
        )
    return VerificationOutcome(
        level=V2_COMPILE,
        passed=True,
        message=f"dbt compile succeeded for model '{model_name}'",
    )


_RUNNERS = {
    V1_STATIC: _run_v1_static,
    V2_COMPILE: _run_v2_compile,
}


def verify_artifact(
    dbt_file_path: str,
    project_dir: str,
    levels: list[str] | None = None,
) -> VerificationReport:
    """Reads the SQL at {project_dir}/{dbt_file_path} FROM DISK -- does NOT
    accept SQL as a string parameter, since V2_COMPILE needs a real file
    dbt can resolve within a real project. Runs each requested level in
    order, STOPPING at the first failure (cheap-first: no point running an
    expensive dbt compile on SQL that doesn't even parse)."""
    levels = DEFAULT_LEVELS if levels is None else levels
    report = VerificationReport(artifact_path=dbt_file_path)
    for level in levels:
        outcome = _RUNNERS[level](project_dir, dbt_file_path)
        report.outcomes.append(outcome)
        if not outcome.passed:
            break
    return report
