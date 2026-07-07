# Blast Radius — Phase 1: Week 1 Foundation (Design)

**Status:** Approved
**Scope:** The first of several sub-projects that together implement the full Blast Radius system described in `docs/blast-radius-project-spec.md` and `docs/blast-radius-kickoff-guide.md`. This phase builds *only* the foundation: repo scaffold, local DataHub instance, Postgres warehouse, dbt demo estate with two deliberately-designed break cases, ingestion, enrichment, and golden outputs. No agent/orchestrator/LLM code ships in this phase — later phases (Assessment Engine, Narrative Builder, Decision Engine, Codegen + Loop 1, Verification Harness, Delivery, Outcome Loop) each get their own design → plan cycle once this foundation is live, per the kickoff guide's own sequencing ("Week 2 starts writing the Assessment Engine against this foundation").

## Why this decomposition

The full spec is a 35-day, multi-subsystem build (5 architectural loops, codegen, verification, GitHub/DataHub write-back). Every agent-side stage reads lineage/ownership/query-history through the DataHub MCP server, so nothing agent-side can be built *or tested* meaningfully until the demo estate exists and is ingested. The kickoff guide's own Week 1/Week 2 split reflects this. Environment probe at design time confirmed a from-zero start: no `datahub` CLI, no containers, no `.env`, no git repo — so Phase 1 is exactly the kickoff guide's Week 1.

## What runs where

Confirmed with the user: infrastructure runs directly on their Mac via the assistant's Bash tool (persists locally, not an ephemeral sandbox), not hand-executed by the user. Docker is available (8 CPUs, 8GB RAM allocated — exactly the stated DataHub minimum, with 4 unrelated containers already running, so quickstart health is watched, not assumed).

## Components

1. **Repo scaffold** (per spec §10 / kickoff §7): `LICENSE` (Apache 2.0), `README.md` stub, `.gitignore`, `.env.example`, `PROVENANCE.md`, `feedback-notes.md`, empty `agent/{orchestrator,loops,assessment,decision,narrative,codegen,verify,dossier}/` packages, `traces/`, `estate/{dbt_project,seeds,ingestion_recipes,golden}/`, `examples/`, `skills/`.
2. **Python environment**: `uv venv --python 3.11` (uv already has CPython 3.11.15 available locally — no pyenv/brew needed). Dependencies: `anthropic`, `openai`, `google-genai`, `sqlglot`, `pygithub`, `dbt-core`, `dbt-postgres`, `pyyaml`, `python-dotenv`, `rich`, `faker`.
3. **LLM provider configuration** (config only in this phase — no call sites yet): the LLM layer is provider-configurable, not hard-wired to one vendor. Anthropic Claude is the default; **OpenRouter, DeepSeek, and Gemini are supported as alternates for now**, selected via `LLM_PROVIDER` in `.env`. OpenRouter and DeepSeek are OpenAI-API-compatible (covered by the `openai` client pointed at each provider's `base_url`); Gemini uses `google-genai`. `.env.example` documents `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, and `LLM_PROVIDER` — only the key(s) for the provider(s) actually in use are required. This is scaffolding only; the client abstraction and call sites belong to the Narrative/Codegen phases.
4. **DataHub**: `datahub docker quickstart` run directly via Bash. Health watched explicitly given the tight memory allocation; if unhealthy, the exact Docker Desktop memory bump needed is reported back (that GUI setting can't be changed programmatically).
5. **Postgres warehouse**: `docker-compose.yml` with its own Postgres service (separate from DataHub's internal MySQL) + a Faker-based seed script producing `raw_customers`, `raw_orders`, `raw_payments` (a few hundred rows, realistic FKs).
6. **dbt project** (jaffle-shop-shaped): staging models `stg_customers` (explicit `select cust_id` — the designed `HARD_BREAK`), `stg_orders`, `stg_payments`; marts `dim_customers`, `fct_orders`, `fct_revenue` (built via `select *` from upstream — the designed `SILENT_CORRUPTION` case).
7. **Ingestion recipes**: YAML recipes for Postgres source (raw layer) and dbt source (staging + marts, lineage + docs), both → `datahub-rest` sink, run via `datahub ingest -c <recipe>`. Airflow DAG metadata and the `revenue_dashboard` entity are hand-authored via small DataHub Python-emitter scripts (standing up real Airflow/BI tooling is correctly out of scope for Week 1 per the kickoff guide).
8. **Enrichment script**: owners per layer, glossary terms (`Customer ID`, `Net Revenue`), docs on key datasets/columns, and ~10–20 representative historical queries registered against the marts so usage-based severity scoring has real signal later.
9. **Golden outputs**: a script runs `dbt build` once pre-change and writes row counts + column checksums for `fct_orders` and `fct_revenue` to `estate/golden/` for later V4 parity checks.
10. **DataHub PAT + MCP wiring**: attempt token creation via DataHub's GraphQL `createAccessToken` mutation using the default `datahub`/`datahub` login (no UI click-through needed); fall back to asking the user to generate it via the UI if that fails. The DataHub MCP server is wired into both Claude Desktop (per kickoff guide §5) and this Claude Code session (so the assistant can call DataHub MCP tools directly for self-verification now and for Week 2+ agent development).

## Division of labor

**Automated (assistant, via Bash):** everything in items 1–10 above except account creation and GUI-only steps.

**Manual (user):** bumping Docker Desktop's memory allocation if quickstart reports unhealthy; restarting Claude Desktop after its MCP config is edited; GitHub PAT and the LLM provider API key(s) — not required until later phases (Delivery, Codegen/Narrative), just documented in `.env.example` now.

## Verification / exit criteria

Matches the kickoff guide's own Week 1 exit criterion:

- `datahub docker quickstart` reports healthy; UI reachable at `localhost:9002`.
- Both ingestion recipes (Postgres, dbt) succeed via `datahub ingest`.
- The kickoff guide's 4-step MCP sanity check (§8) passes, replicated by the assistant directly over MCP: search `raw_customers` + schema fields; downstream lineage for `raw_customers.cust_id`; queries against `fct_revenue`; propose a tag/description mutation.
- `estate/golden/` contains row-count + checksum files for `fct_orders` and `fct_revenue`.
- Full lineage from `raw_customers` down to `revenue_dashboard` is visible and correct in the DataHub UI.

## Out of scope for this phase

Orchestrator, Assessment Engine, Decision Engine, Narrative Builder, Codegen, Verification Harness (agent-side), Dossier renderer, GitHub PR automation, DataHub write-back proposals, all five Loops' runtime behavior. These are each a separate sub-project with their own design → plan cycle, built against this foundation once it's live.
