# large-blast-defer

**This one is synthetic input, real code.** This project's own demo estate is deliberately small — "small but deep, one killer change exercises everything" — so it never naturally reaches the Decision Engine's Strategy-C (defer) thresholds (`DEFER_HARD_BREAK_THRESHOLD=5` hard breaks, or `DEFER_DEEPEST_HOP_THRESHOLD=4` affected-hop depth; see `agent/decision/engine.py`). To show that branch of the judgment spectrum honestly rather than skip it, `generate.py` fabricates an `AssessmentResult` shaped like a larger organization's lineage graph (7 hard breaks spanning hop 1–4, two dashboard-exposed) and runs it through the **real, unmodified** `decide_migration` / `build_narratives` / `render_dossier` functions. Nothing about the decision logic, narrative generation, or rendering is faked — only the input assessment data is.

**Decision:** BREAKING — Strategy C (defer & deprecate). Both A (direct patch) and B (bridge) are correctly rejected: A because 7 simultaneous consumer patches is too much surface area for one PR, B because a bridge still requires patching every consumer eventually across a chain this deep — the risk is the blast radius itself, which a bridge doesn't shrink.

No codegen or verification runs for a deferred decision (there's nothing to generate yet — see the dossier's "DEFERRED" banner, which is deliberately worded differently from the ADDITIVE/NO_MIGRATION_NEEDED cases in the other two examples: a fix genuinely *is* needed here, just not generated until a human signs off on the deprecation path).

Reproduce:

```bash
source .venv/bin/activate
python examples/large-blast-defer/generate.py
```

Files:
- `generate.py` — the fabricated `AssessmentResult` plus the real pipeline calls that turn it into a dossier. Read this file to see exactly what's fabricated (hop/severity/ownership data) vs. real (every function call).
- `dossier-output.txt` — the generated dossier.
