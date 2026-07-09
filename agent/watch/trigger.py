"""Loop 5 (Watch Mode) -- trigger: turns already-computed `DetectedChange`s
into pipeline runs. Pure orchestration -- no I/O, no MCP calls -- the caller
(agent/watch/cli.py) is responsible for capture+diff before calling this.
"""
from __future__ import annotations

from typing import Callable

from agent.watch.models import DetectedChange

PipelineFn = Callable[[str, str, str, str, str, str], dict]


def _default_pipeline_fn(
    table: str, old_column: str, new_column: str, change_type: str, schema: str, platform: str
) -> dict:
    """Lazily imports `agent.dossier.pipeline.run_full_pipeline` -- inside
    this function body, NOT at module import time -- so `agent/watch/*` and
    its tests work regardless of whether `agent/dossier/pipeline.py` (a
    parallel Phase 7 build) exists yet. The import only fires when there is
    an actual actionable change to hand off (see `run_watch_cycle`), never
    just because `pipeline_fn` was left as the default.

    `schema`/`platform` come from the DetectedChange that triggered this
    call (ultimately from the SchemaSnapshot that was diffed) -- without
    threading them through, this would silently fall back to
    run_full_pipeline's schema="public"/platform="postgres" defaults even
    when watch mode was pointed at a different one, re-resolving the change
    against the wrong table.

    `auto_approve_decision=False, create_pr_live=False` are hardcoded and
    non-overridable here: an autonomously-triggered detection must never
    auto-approve a migration strategy or create a live PR without a human in
    the loop. Watch mode's value is *surfacing* the detected change and a
    proposed fix for review -- not acting on it unattended.
    """
    from agent.dossier.pipeline import run_full_pipeline

    return run_full_pipeline(
        table,
        old_column,
        new_column,
        change_type,
        schema=schema,
        platform=platform,
        auto_approve_decision=False,
        create_pr_live=False,
    )


def run_watch_cycle(
    changes: list[DetectedChange],
    pipeline_fn: PipelineFn | None = None,
) -> list[dict]:
    """For each `DetectedChange` in `changes`, calls
    `pipeline_fn(change.table, change.old_column, change.new_column,
    change.change_type, change.schema, change.platform)` -- skipping any
    change where `old_column` or `new_column` is None (a bare
    `add_column`/`drop_column` isn't a migration this pipeline can act on
    the way a rename is; it's just recorded as seen, not handed to the
    pipeline).

    Returns a list of `{"change": DetectedChange, "result": <whatever
    pipeline_fn returned>}` for each call actually made -- changes that were
    skipped are simply absent from the return value (the caller still has
    the full `changes` list to report on those separately).

    `pipeline_fn` defaults to `None`, in which case a thin wrapper around
    the lazily-imported real pipeline is used (see `_default_pipeline_fn`).
    Because that wrapper is only *referenced*, not called, until there's an
    actionable change in `changes`, `run_watch_cycle([], pipeline_fn=None)`
    (and an all-add/drop `changes` list) never touches `agent.dossier` at
    all -- important since that module may not exist yet.
    """
    fn: PipelineFn = pipeline_fn if pipeline_fn is not None else _default_pipeline_fn

    triggered: list[dict] = []
    for change in changes:
        if change.old_column is None or change.new_column is None:
            continue
        result = fn(change.table, change.old_column, change.new_column, change.change_type, change.schema, change.platform)
        triggered.append({"change": change, "result": result})
    return triggered
