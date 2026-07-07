# Blast Radius — Project Specification (v3, Final: Change Intelligence + Loop Engineering)

**A schema-change intelligence and migration copilot built on DataHub.**
*Blast Radius explains what broke, why, and how; decides whether a migration is even needed; generates the fix and self-corrects until it verifiably works; delivers it as a PR your team would actually merge; and confirms the migration succeeded after it lands.*

**Hackathon:** Build with DataHub: The Agent Hackathon
**Challenge Category:** Metadata-Aware Code Generation & Development (Category 2)
**Required tooling compliance:** Built on **DataHub Core (open-source)** together with the **DataHub MCP Server**
**License:** Apache 2.0

---

## 1. Design Philosophy: Information First, Fixes Second

A fix nobody understands is a fix nobody trusts — and a fix nobody trusts doesn't get merged. Blast Radius is an **answering machine before it is a patching machine**. Every run must answer, in plain language and with evidence, the questions an engineer would ask a competent colleague:

1. **What broke?** (and what *didn't* — equally important)
2. **Why did it break?** (the causal dependency chain, with evidence)
3. **How did it break?** (the failure mechanism — loud crash vs. silent corruption)
4. **How severe is it?** (ranked by real usage, ownership, and exposure)
5. **Does this even need a migration?** (sometimes the right answer is "no")
6. **What are the fix options, and which do we recommend?** (with trade-offs)
7. **Does the fix actually work?** (proven, not promised)
8. **Did the migration succeed after merging?** (the loop closes, in writing)

Every answer lands in one artifact — the **Impact Dossier** — which travels as the PR description, attaches to affected assets in DataHub, and is archived in the repo. Six months later, the change explains itself.

A second principle joins it in v3: **every loop has a cap, an exit, and a trace.** The agent is engineered as a system of five bounded, observable loops (§4) — no unbounded retries, no opaque reasoning, no loop that can't explain why it stopped.

---

## 2. The Problem

A column gets renamed, retyped, or dropped upstream. That one-line change silently propagates through staging models, marts, pipeline DAGs, and dashboards. Today the engineer greps repos, squints at lineage graphs, Slacks "does anyone still use `cust_id`?", hand-patches whatever they find — and still misses the finance dashboard that breaks Monday morning. Even when things get fixed, *nobody writes down what happened*, so the organization learns nothing and the next change repeats the ordeal.

The knowledge to do this properly — what depends on what, who owns it, how it's really queried — already exists in DataHub. Blast Radius wires that knowledge into the act of changing code, and wires what it learns back in.

---

## 3. The Pipeline: Detect → Assess → Explain → Decide → Generate → Verify → Deliver → Confirm

### Stage 0 — Detect / Declare (trigger)
- **Declared mode:** an engineer states an intended change (`rename customers.cust_id → customer_id`) via CLI or minimal UI.
- **Watch mode (Loop 5 entry):** the agent monitors schema metadata across ingestion runs; an *unannounced* schema diff — the real-world failure case — triggers the pipeline autonomously.

### Stage 1 — Assess: *what broke, and how badly?* (Impact Assessment Engine)
Reading DataHub through the MCP Server (Loop 2 territory — see §4), the agent traverses downstream lineage to full depth and, for **every** downstream asset, determines:

- **Break mode (how it breaks):**
  - `HARD_BREAK` — SQL references the old column explicitly; compilation/execution fails loudly (e.g., `stg_customers.sql` line 12 selects `cust_id`).
  - `SILENT_CORRUPTION` — the worst kind: `SELECT *` propagation shifting columns, implicit type coercion after a type change, joins quietly producing NULLs. Nothing crashes; the numbers just go wrong.
  - `DEGRADED` — still works but worse: lost index/partition alignment, doc/glossary drift.
  - `UNAFFECTED` — downstream but untouched by the changed field. Explicitly listed, because telling users what's *safe* is half the value.
- **Severity score:** `break_mode weight × usage frequency (DataHub query history) × exposure (dashboard-facing vs. internal) × ownership criticality (domain/tier tags)` → a ranked severity matrix, not an undifferentiated list.
- **Blast summary stats:** N scanned, N affected, N hard breaks, N silent risks, N owners, deepest hop.

### Stage 2 — Explain: *why and how, with evidence* (Causal Narrative Builder)
For each affected asset, a plain-English causal chain backed by verifiable evidence:

> `fct_revenue` breaks **because** it aggregates `dim_customers.customer_key`, **which is derived from** `stg_customers.cust_id` (line 12 of `stg_customers.sql`), **which maps to** the renamed physical column. **Mechanism:** dbt compilation error at staging — this break is *loud*. **However,** `revenue_dashboard` reads `fct_revenue` via `SELECT *` — a wrong patch here would break *silently*. **Evidence:** 4-hop lineage path (visualized), the referencing SQL line, 37 user queries in the last 30 days.

The LLM writes the narrative; deterministic traversal supplies every fact — readable *and* auditable.

### Stage 3 — Decide: *does this actually need a migration?* (Migration Decision Engine)
Before generating anything, the agent answers the question most tools never ask:

- **No migration needed** — zero downstream references (verified by traversal + AST scan). Action: metadata-only update + a dossier stating *why nothing else is required*. Saying "don't migrate" when true is a feature and a trust-builder.
- **Additive / non-breaking** — new nullable column, lossless type widening. Action: documentation proposal only; consumers notified, not patched.
- **Breaking — options analysis**, 2–3 strategies with explicit trade-offs and a recommendation:
  - **A. Direct patch** — every consumer in one PR. *Clean, atomic; big-bang risk.* For small, fully covered blast radii.
  - **B. Bridge migration** — compatibility view aliasing old → new, patch consumers, schedule bridge removal. *Zero-downtime, gradual.* For high-exposure consumers.
  - **C. Defer & deprecate** — blast radius too large/risky; recommend a deprecation cycle with owner sign-offs. *The agent advising "not yet" is judgment, not failure.*
- The chosen strategy (human confirms in declared mode — Loop 4 gate; policy default in watch mode) is **recorded with its rationale and the rejected alternatives.**

### Stage 4 — Generate: *the fix itself* (Codegen Layer)
Per strategy: patched dbt model SQL + `schema.yml`, updated Airflow DAG code, bridge-view migration script where applicable, updated docs. Generation is **template-anchored** — Jinja skeletons define structure; the LLM fills constrained slots — deterministic where it must be, fluent where it may be. Every artifact exits this stage *only through Loop 1* (§4).

### Stage 5 — Verify: *does the fix work? Prove it.* (Verification Harness ↔ Loop 1 + Loop 3)
Nothing ships on faith. Every artifact runs the gauntlet, ordered by cost so failures are caught cheaply:

| Level | Check | Question answered | On failure |
|---|---|---|---|
| **V1 — Static** | `sqlglot` parse + dialect validation | "Is this valid SQL?" | → Loop 1 regenerate |
| **V2 — Compile** | `dbt parse` / `dbt compile` of patched project | "Does the project still build?" | → Loop 1 regenerate |
| **V3 — Execute** | `dbt build` into an isolated **shadow schema** | "Does it actually run end-to-end?" | → Loop 1 regenerate |
| **V4 — Data parity** | Row counts + column checksums vs. golden outputs | "Are the *numbers* still right?" (silent-corruption detector) | → Loop 1, or escalate if semantic |
| **V5 — Residue scan** | AST scan of the repo for orphan references | "Did we miss anything?" | → re-assess missed asset |

The full verification report — pass/fail per level per artifact, parity diffs, and **self-correction history** (how many regeneration attempts each artifact needed, and why) — is embedded in the PR as a check-style status table. Proof before diffs.

### Stage 6 — Deliver: *the PR and the knowledge*
- **GitHub PR:** branch → commits → PR whose description **is the Impact Dossier**, with DataHub-identified owners requested as reviewers (Loop 4 gate #2).
- **DataHub write-back (governed):** via MCP mutation/proposal tools through the Proposals workflow — deprecation tag, updated descriptions, structured property linking assets to the PR, dossier as documentation. Agent proposes; human approves in the DataHub UI (Loop 4 gate #3).

### Stage 7 — Confirm: *did the migration succeed?* (Outcome Loop — Loop 5 exit)
- The agent watches the PR; on merge it re-ingests, re-traverses lineage, and re-runs V2/V3/V5 against the *real* post-merge state.
- It writes a **Migration Outcome Record** to DataHub: `SUCCEEDED` / `PARTIAL` / `FAILED`, evidence links, timestamp, and bridge-removal reminder where applicable.
- **On failure:** the bridge view is the built-in safety net; the agent generates a revert PR and an updated dossier explaining what diverged from prediction.
- Owners get a closure report: *"Migration #42: succeeded. 7 assets patched, parity verified, deprecation approved. Bridge removal Aug 30."*

---

## 4. Loop Engineering: The Five Loops (new in v3)

Blast Radius is architected as five nested, bounded loops. The governing rule for all of them: **every loop has a cap, an exit, and a trace** — bounded retries, deterministic termination, logged reasoning. This section defines each loop, its depth commitment for the hackathon build, and how it surfaces in the demo.

### Loop 1 — The Self-Correction Loop ⭐ *(the signature loop — fully polished)*

**Cycle:** `generate → validate → inject failure evidence → regenerate` — capped at **3 attempts per artifact**, then escalate.

This is the load-bearing loop and the feature that makes Category 2's promise — *"code that works on the first try"* — literally true from the user's perspective: the agent absorbs its own failures internally, so the human only ever sees validated output.

**Mechanics:**
- When any verification level (V1–V4) fails, the loop captures the **exact failure evidence** — the sqlglot parse error, the dbt compile message (`column "customer_key" does not exist in dim_customers`), the parity diff — and injects it into the LLM's regeneration context alongside the failing artifact and the original DataHub-derived constraints.
- Regeneration is *targeted*: only the failing artifact re-enters the loop; passing artifacts are frozen. The template anchor never changes — only the LLM-filled slots regenerate — so self-correction can't drift the structure.
- **Attempt cap = 3.** On exhaustion the artifact is marked `NEEDS_HUMAN` in the dossier with the full attempt history — the agent fails *informatively*, never silently and never infinitely.
- **Every cycle is traced:** attempt number, failure evidence, what changed between attempts, final verdict. Traces are written to `traces/` and summarized in the PR's verification table ("`stg_customers.sql`: passed on attempt 2 — V2 failure: unresolved ref, corrected join alias").

**Why it's the star:** it's the only loop judges can *watch working*. Ten seconds of trace footage — `V2 failed → error injected → regenerated → V2 passed` — proves genuine reasoning better than any architecture slide. It also compounds: Loop 3's gauntlet is only useful because failures route here, and watch mode is only trustworthy because everything it autonomously ships passed through here.

### Loop 2 — The Reasoning Loop *(structured and bounded)*

**Cycle:** `plan → MCP call → observe → update plan`, operating inside Stages 1–3.

**Discipline:** no freeform ReAct wandering. The pipeline stages *are* the plan; this loop only makes bounded micro-decisions — "traverse one hop deeper?", "fetch query history for this asset?", "is this `SELECT *` worth flagging?" — under a **max lineage depth** and a **tool-call budget per run**. Every MCP call and its one-line rationale is logged to the trace. A staged loop that always terminates beats an autonomous-sounding one that occasionally spirals.

### Loop 3 — The Verification Gauntlet *(V1–V3 committed; V4–V5 stretch)*

**Cycle:** `check level N → pass ? advance : route to Loop 1 (or escalate)`.

Levels are **ordered by cost** — parse before compile before shadow-execution before parity — so cheap checks absorb most failures and expensive checks run only on near-final artifacts. The gauntlet and Loop 1 are gears in one machine: Loop 3 finds problems, Loop 1 fixes them, Loop 3 confirms.

### Loop 4 — The Human Gates *(all three shipped — they're free)*

Three deliberate pause points where the system yields to human judgment: **strategy confirmation** (Decision Engine, declared mode), **PR review** (GitHub), **proposal approval** (DataHub Proposals). These are not weaknesses to apologize for — they're the brakes, and the dossier is engineered so each gate's decision takes minutes, not hours. Presented in the demo as the maturity signal they are: the agent proposes, humans dispose.

### Loop 5 — The Outer System Loop *(watch + outcome shipped; learning deferred)*

**Cycle:** `watch → detect → act (Stages 1–6) → confirm outcome → [learn]`.

Watch mode closes detection-to-repair; the Outcome Record closes repair-to-confirmation. The final arc — outcome records feeding back into severity scoring so the agent learns from *actual* organizational breakage history — is real loop engineering but a multi-week project that can't be demoed convincingly on a three-week-old synthetic estate. **It ships as Future Scope**, stated honestly: the data model for it (outcome records as structured properties) is already in place, which is the credible half of the promise.

### Loop depth commitments (summary)

| Loop | Depth shipped | Demo surface |
|---|---|---|
| 1 — Self-correction | **Full, polished, traced** — the signature | Trace log: fail → inject → regenerate → pass |
| 2 — Reasoning | Structured, bounded, logged | MCP call trace with rationales |
| 3 — Gauntlet | V1–V3 committed; V4–V5 stretch | Verification status table in PR |
| 4 — Human gates | All three | Strategy prompt · PR review · DataHub approval |
| 5 — Outer system | Watch mode + Outcome Record; learning → Future Scope | Unprompted catch (open) · outcome on asset (close) |

---

## 5. The Impact Dossier (the flagship artifact)

One document, fixed structure, generated every run — §1's eight questions answered in order, now including loop evidence:

```
IMPACT DOSSIER — Change #42: rename raw_customers.cust_id → customer_id
├── 1. Blast Summary        7 affected / 12 scanned · 3 hard · 2 silent-risk · 2 degraded · 5 safe
├── 2. Severity Matrix      ranked: asset · break mode · usage · exposure · owner
├── 3. Causal Narratives    per-asset why/how, lineage paths + file:line evidence
├── 4. Migration Decision   NEEDED — Strategy B (bridge) · rationale · rejected: A, C (reasons)
├── 5. Generated Artifacts  file list with per-file purpose annotations
├── 6. Verification Report  V1–V5 results · parity diffs · self-correction history per artifact
├── 7. Rollback Plan        bridge view retained; revert path documented
└── 8. Outcome              (post-merge) SUCCEEDED · evidence · bridge removal: Aug 30
```

Rendered three ways: PR description (Markdown), DataHub documentation on affected assets (via proposals), archived in `examples/` for judges.

---

## 6. Why This Wins (Criteria Impact)

| Criterion | How v3 delivers |
|---|---|
| **Use of DataHub** *(tiebreaker #1)* | Read-deep: lineage, schemas, ownership, docs, query history all drive assessment. Write-deep: dossiers, deprecation proposals, outcome records return through governed Proposals. |
| **Technical Execution** | The self-correction loop + verification gauntlet turn "it works" into on-screen evidence, including the failure-and-recovery cases most demos hide. Bounded loops with traces demonstrate engineering discipline, not just capability. |
| **Originality** | Impact explanation + migration decision-making + self-correcting generation + verification + outcome confirmation is a lifecycle no shipped DataHub feature covers — clearly past both chat-agents (collides with Analytics Agent) and alert-guardians (April's winning pattern). Detection is our opening scene; the verified repair is the punchline. |
| **Real-World Usefulness** | Engineers don't merge unexplained diffs. The dossier mirrors how real teams review change: evidence, options, proof, rollback. "Sometimes recommends *not* migrating" is the detail practitioners love. |
| **Submission Quality** | The dossier is screenshot-gold; the trace log gives the video a moment of visible *thinking*; `examples/` shows the judgment spectrum, not three sizes of the same rename. |
| **Bonus (OSS)** | The impact-analysis workflow packaged as a reusable DataHub Skill and/or an upstream PR/RFC born from build friction (logged in `feedback-notes.md`, which also feeds the Feedback Prize submission). |

---

## 7. Architecture

```
                 ┌──────────────────────────────────────────────────────────────┐
                 │              Blast Radius Agent (Python 3.11)                  │
 CLI / min UI ───┤                                                                │
 Watch poller ───┤  Orchestrator: detect → assess → explain → decide →            │
 (Loop 5)        │                generate → verify → deliver → confirm           │
                 │                                                                │
                 │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐ │
                 │  │ Assessment    │ │ Decision      │ │ Codegen                │ │
                 │  │ Engine        │ │ Engine        │ │ Jinja + LLM slot-fill  │ │
                 │  │ (Loop 2)      │ │ (Loop 4 gate) │ │        ▲               │ │
                 │  └──────────────┘ └──────────────┘ │        │ regenerate     │ │
                 │  ┌──────────────┐ ┌──────────────┐ │  ┌─────┴─────────────┐  │ │
                 │  │ Narrative     │ │ Dossier       │ │  │ Loop 1 Controller │  │ │
                 │  │ Builder       │ │ Renderer      │ │  │ failure evidence  │  │ │
                 │  └──────────────┘ └──────────────┘ │  │ injection · cap=3 │  │ │
                 │  ┌────────────────────────────────┐│  │ · trace writer    │  │ │
                 │  │ Verification Harness V1–V5      ││  └───────────────────┘  │ │
                 │  │ (Loop 3) ── fail ──────────────┼┘                          │ │
                 │  └────────────────────────────────┘                           │ │
                 └────────┬─────────────────────┬────────────────┬──────────────┘
                          │ MCP (read+write)    │ REST           │ SQL
                  ┌───────▼────────┐    ┌───────▼──────┐  ┌──────▼─────────┐
                  │ DataHub Core   │    │ GitHub API    │  │ Warehouse       │
                  │ (quickstart) + │    │ PR + reviewers│  │ (Postgres) +    │
                  │ MCP Server     │    │ + merge watch │  │ shadow schema   │
                  └───────┬────────┘    └──────────────┘  └────────────────┘
                          │
                  ┌───────▼──────────────────────────────────────┐
                  │ Demo estate: raw → dbt staging → marts →      │
                  │ dashboard · Airflow DAG · owners · glossary · │
                  │ ingested query history · golden outputs (V4) │
                  └───────────────────────────────────────────────┘
```

Key notes: MCP read tools (search, schema fields, lineage, ownership, docs, query history) feed Assessment under Loop 2's budget; the Loop 1 Controller sits between Codegen and the Harness, owning retry state, evidence injection, and traces; MCP mutation/proposal tools carry dossiers and outcome records back through governed Proposals; the shadow schema sandboxes V3/V4; every stage logs to `traces/` so the video can show *how the agent thinks*. The LLM calls in Narrative (Stage 2) and Codegen (Stage 4) go through a thin, **provider-configurable** client — Anthropic Claude by default, with OpenRouter, DeepSeek, and Gemini supported as alternates for now — so model choice is a config value, not a code fork.

---

## 8. Demo Data Estate

Small but deep — one killer change exercises everything:

- **Raw (Postgres):** `raw_customers`, `raw_orders`, `raw_payments`
- **Staging (dbt):** `stg_customers` (explicit `cust_id` reference → HARD_BREAK), `stg_orders`, `stg_payments`
- **Marts (dbt):** `dim_customers`, `fct_orders`, `fct_revenue` (one mart uses `SELECT *` → SILENT_CORRUPTION showcase)
- **Consumption:** `revenue_dashboard` asset
- **Pipeline:** Airflow DAG metadata
- **Enrichment:** per-layer owners, glossary terms, docs, **ingested query history** (makes usage-ranking real)
- **Golden copies** of mart outputs for V4 parity

The canonical change — `raw_customers.cust_id` → `customer_id` — deliberately produces *both* a loud break and a silent-corruption risk, so the demo shows the agent distinguishing them. The estate also includes one deliberately tricky model designed to make the first generation attempt fail — so the self-correction loop fires *on camera*, honestly.

---

## 9. Demo Script (< 3 min)

| Time | Scene |
|---|---|
| 0:00–0:15 | Problem over a lineage graph. Category + tooling stated: *DataHub Core via the DataHub MCP Server*. |
| 0:15–0:35 | **The break:** column renamed in Postgres, re-ingested. Watch mode catches it — unprompted (Loop 5 opens). |
| 0:35–1:10 | **The intelligence:** severity matrix — "3 loud breaks, 2 silent risks, 5 confirmed safe." One causal narrative with file:line evidence. Decision Engine picks Strategy B on screen, rationale + rejected options shown. |
| 1:10–1:45 | **The self-correction moment ⭐:** trace log live — `V2 failed: unresolved ref → error injected → regenerated → passed (attempt 2)`. Then the gauntlet completes V1→V3, parity passes. |
| 1:45–2:20 | **The money shot:** GitHub PR opens — dossier as description, owners tagged, verification table with self-correction history — cut to DataHub UI, deprecation proposal awaiting approval. |
| 2:20–2:40 | **The loop closes:** merge → Outcome Record `SUCCEEDED` appears on the asset in DataHub (Loop 5 closes). |
| 2:40–3:00 | Architecture flash · `examples/` flash · OSS contribution · one-liner. |

*(No music, no third-party trademarks beyond functional UI — per rules.)*

---

## 10. Repository Layout

```
blast-radius/
├── LICENSE                  # Apache 2.0 — set as repo license (visible in About)
├── README.md                # what/why/how · architecture · loop engineering · setup · Provenance
├── docker-compose.yml       # one command: DataHub + Postgres + seeded estate
├── agent/
│   ├── orchestrator/        # pipeline stages
│   ├── loops/               # Loop 1 controller (retry state, evidence injection, caps)
│   │                        # + Loop 2 budget/depth guards + Loop 5 watch/outcome
│   ├── assessment/          # break modes, severity scoring
│   ├── decision/            # migration decision engine
│   ├── narrative/           # causal explanation builder
│   ├── codegen/             # Jinja templates + LLM slot-fill
│   ├── verify/              # V1–V5 harness (Loop 3)
│   └── dossier/             # renderer (PR / DataHub / archive)
├── traces/                  # per-run reasoning + self-correction traces (demo gold)
├── estate/                  # dbt project, seeds, ingestion recipes, golden outputs
├── examples/                # 3 complete runs, each with full dossier + generated PR + trace
│   ├── simple-rename/       #   incl. a "no migration needed" verdict
│   ├── type-change-silent/  #   V4 parity catching silent corruption
│   └── large-blast-defer/   #   Decision Engine recommending Strategy C
├── skills/                  # packaged DataHub Skill (OSS contribution)
└── feedback-notes.md        # running log → Feedback Submission + OSS PR fodder
```

---

## 11. Scope Ladder (final, loop-aware)

**MVP (must ship):** declared-change flow → assessment (break modes + severity) → causal narratives → dbt patch generation **wrapped in Loop 1 (self-correction with V1+V2, cap 3, traced)** → PR with dossier → proposal write-back. Loop 2 bounded; Loop 4 gates all present.
**Target:** + watch mode (Loop 5 open) · + Decision Engine A/B/C · + V3 shadow-schema execution · + Airflow patching · + bridge-view strategy · + Outcome Record (Loop 5 close, manual trigger acceptable).
**Stretch:** V4 data parity · V5 residue scan · fully automated merge-watch · minimal web UI.
**Explicitly deferred:** Loop 5's learning arc (outcomes retraining severity scoring) → Future Scope, with the data model already in place.
**Cut order if behind:** web UI → merge-watch automation (demo manually) → V4/V5 → Airflow patcher.
**Never cut:** Loop 1 with visible traces, assessment + severity matrix, causal narratives with evidence, dossier, dbt PR generation, write-back, video quality, `examples/`.

---

## 12. Future Scope (submission narrative)

- **Learning loop:** Migration Outcome Records retrain severity scoring on the organization's *actual* breakage history — the data model ships now; the learning ships next.
- CI-gate mode: Blast Radius as a required check on any PR touching warehouse DDL.
- Prefect/Dagster patching; BI-tool (Looker/Superset) impact analysis.
- Team mode: batched change-windows → one consolidated migration PR + dossier.

---

## 13. One-Liner

> **"Blast Radius doesn't just fix your schema change — it tells you what breaks, corrects itself until the fix provably works, and writes down what happened. The repair is the receipt."**
