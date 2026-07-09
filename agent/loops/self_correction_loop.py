"""Loop 1 -- The Self-Correction Loop (spec's signature loop):
generate -> validate -> inject failure evidence -> regenerate, capped at 3
attempts, fully traced.

This controller is generation-mechanism-agnostic: it owns the retry/evidence
plumbing and the disk write, and delegates the actual candidate generation
(`generate_fn`) and verification (`verify_fn`) to injected callables. In
production, `generate_fn` closes over agent.codegen.generator.generate_patch
(+ a real or template-fallback LLM client) and `verify_fn` defaults to
agent.verify.harness.verify_artifact -- imported lazily inside
`run_self_correction` (not at module top-level) so this module -- and its own
unit tests -- work correctly even before agent/verify/ exists on disk, since
that package is being built in parallel.

Tracing follows the exact convention used by agent/loops/reasoning_loop.py's
`write_trace`: one JSON object per line, under traces/<run_id>.jsonl.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from agent.verify.models import VerificationReport

TRACES_DIR = Path(__file__).resolve().parents[2] / "traces"

PASSED = "PASSED"
NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass
class AttemptRecord:
    attempt_number: int
    candidate_content: str
    verification: "VerificationReport"  # from agent.verify.models


@dataclass
class SelfCorrectionResult:
    dbt_file_path: str
    attempts: list[AttemptRecord] = field(default_factory=list)
    final_status: str = PASSED  # "PASSED" | "NEEDS_HUMAN"
    run_id: str = ""  # populated by run_self_correction -- names traces/<run_id>.jsonl

    def write_trace(self) -> Path:
        """Writes one JSON line per attempt to traces/<run_id>.jsonl -- same
        format/style as agent/loops/reasoning_loop.py's write_trace: enough
        per line to reconstruct what happened on that attempt without
        needing the other lines."""
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACES_DIR / f"{self.run_id}.jsonl"
        with path.open("w") as f:
            for attempt in self.attempts:
                verification = attempt.verification
                first_failure = None if verification.passed else verification.first_failure
                f.write(
                    json.dumps(
                        {
                            "attempt_number": attempt.attempt_number,
                            "dbt_file_path": self.dbt_file_path,
                            "candidate_content": attempt.candidate_content,
                            "passed": verification.passed,
                            "outcomes": [
                                {
                                    "level": outcome.level,
                                    "passed": outcome.passed,
                                    "message": outcome.message,
                                    "raw_error": outcome.raw_error,
                                }
                                for outcome in verification.outcomes
                            ],
                            "first_failure_raw_error": (first_failure.raw_error if first_failure else None),
                        }
                    )
                    + "\n"
                )
        return path


def run_self_correction(
    dbt_file_path: str,  # project-relative, e.g. "models/staging/stg_customers.sql"
    project_dir: str,  # absolute path to a dbt project root -- caller's responsibility to point this at a temp copy, never the real estate/dbt_project
    generate_fn: Callable[[str | None], str],  # (failure_evidence_or_None) -> full candidate file content; called once per attempt
    max_attempts: int = 3,
    verification_levels: list[str] | None = None,  # forwarded to verify_fn; None means verify_fn's own default
    verify_fn: Callable[[str, str, list[str] | None], "VerificationReport"] | None = None,
) -> SelfCorrectionResult:
    """Owns writing generate_fn's output to {project_dir}/{dbt_file_path} on
    disk BEFORE calling verify_fn -- verify_fn only ever reads. On failure,
    passes verification.first_failure.raw_error as the failure_evidence
    argument to the next generate_fn call. Traces every attempt (attempt
    number, verification outcome, pass/fail) to traces/<run_id>.jsonl.
    """
    if max_attempts < 1:
        # SelfCorrectionResult.final_status defaults to PASSED -- if the
        # loop below never runs (empty range), that default would leak out
        # unchanged, reporting a false PASSED with zero attempts instead of
        # the caller's invalid input.
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")

    if verify_fn is None:
        # Lazy import: agent/verify/ is being built in parallel and may not
        # exist on disk yet when this module is imported/tested. Only
        # resolved at call time, and only when the caller hasn't injected a
        # fake -- so this module and its own tests work regardless of
        # whether agent/verify/harness.py exists yet.
        from agent.verify.harness import verify_artifact as verify_fn

    run_id = f"selfcorrect-{uuid.uuid4().hex[:8]}"
    result = SelfCorrectionResult(dbt_file_path=dbt_file_path, run_id=run_id)

    target_path = Path(project_dir) / dbt_file_path
    failure_evidence: str | None = None

    try:
        for attempt_number in range(1, max_attempts + 1):
            candidate_content = generate_fn(failure_evidence)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(candidate_content)

            verification = verify_fn(dbt_file_path, project_dir, verification_levels)

            result.attempts.append(
                AttemptRecord(
                    attempt_number=attempt_number,
                    candidate_content=candidate_content,
                    verification=verification,
                )
            )

            if verification.passed:
                result.final_status = PASSED
                break

            result.final_status = NEEDS_HUMAN
            failure_evidence = verification.first_failure.raw_error if verification.first_failure else None
    finally:
        # generate_fn/verify_fn can raise on a genuine infra problem (e.g.
        # dbt not on PATH) rather than a verification failure -- that's a
        # real error the caller must see (retrying won't fix a broken
        # environment), but whatever attempts already ran must still be
        # traced rather than lost, so the audit trail survives the crash.
        result.write_trace()

    return result
