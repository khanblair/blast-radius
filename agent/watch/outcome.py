"""Loop 5 (Watch Mode) -- outcome log: a minimal, append-only record of what
watch mode has detected and (where applicable) triggered over time.

Intentionally lightweight -- the spec calls Loop 5's full feedback/ML arc
(outcomes feeding back into severity scoring) a "deferred learning arc" and
explicit Future Scope. This is just enough of a breadcrumb trail to
reconstruct what happened later; no aggregation or analysis lives here.
"""
from __future__ import annotations

import json
from pathlib import Path


def record_outcome(entry: dict, log_path: Path) -> None:
    """Appends one JSON line to `log_path`, creating it and any parent
    directories if needed. `entry` should include at least a timestamp
    (supplied by the caller, not computed here) and enough of the detected
    change + pipeline result to reconstruct what happened later.

    Deliberately accepts any caller-supplied path with no root confinement
    (see agent/watch/cli.py's --outcome-log) -- this is a shared utility,
    not a trust boundary, and path validation belongs where the untrusted
    CLI argument first enters, not re-derived here."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def read_outcomes(log_path: Path) -> list[dict]:
    """Reads all recorded outcomes back, in append order. Empty list if the
    file doesn't exist yet."""
    if not log_path.exists():
        return []
    with log_path.open() as f:
        return [json.loads(line) for line in f if line.strip()]
