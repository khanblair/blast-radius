"""Shared filesystem-path safety helper.

pythonsecurity:S8707 -- every CLI in agent/ (dossier, narrative, orchestrator,
watch) is meant to be driven by an LLM agent (spec's whole premise), so a
faulty or adversarial --output/--json-out/--outcome-log argument must not be
able to escape the intended output directory via `..` traversal or an
absolute path pointing elsewhere on disk. This is the one place that check
lives, so every CLI validates the same way instead of re-deriving it.
"""
from __future__ import annotations

from pathlib import Path


class UnsafeOutputPathError(ValueError):
    """Raised when a caller-supplied path resolves outside the allowed root."""


def safe_output_path(raw_path: str | Path, *, root: Path | None = None) -> Path:
    """Resolves `raw_path` against `root` (default: cwd) and confirms the
    result doesn't escape `root`, before any caller writes to it. Relative
    paths are joined to `root` first; absolute paths are checked as-is."""
    root = (root or Path.cwd()).resolve()
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise UnsafeOutputPathError(f"Output path {raw_path!r} resolves outside the allowed root {root}")
    return resolved
