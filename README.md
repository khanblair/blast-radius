# Blast Radius

**A schema-change intelligence and migration copilot built on DataHub.**

Blast Radius explains what broke, why, and how; decides whether a migration is even needed; generates the fix and self-corrects until it verifiably works; delivers it as a PR your team would actually merge; and confirms the migration succeeded after it lands.

**Hackathon:** Build with DataHub: The Agent Hackathon
**Challenge category:** Metadata-Aware Code Generation & Development (Category 2)
**Built on:** DataHub Core (open-source) + the DataHub MCP Server
**License:** Apache 2.0

Full design: [`docs/blast-radius-project-spec.md`](docs/blast-radius-project-spec.md). Kickoff/setup guide: [`docs/blast-radius-kickoff-guide.md`](docs/blast-radius-kickoff-guide.md). Runnable demo script: [`docs/demo-script.md`](docs/demo-script.md).

## Status

All 9 build phases complete. 184 tests passing (`python -m pytest tests/`).

| Phase | What it built |
|---|---|
| 1 | Foundation: local DataHub instance, Postgres warehouse, dbt demo estate (deliberate `HARD_BREAK` + `SILENT_CORRUPTION` cases), ingestion, enrichment, golden outputs. |
| 2 | Assessment Engine (Loop 2 + Stage 1) — structural break-mode classification, severity scoring. |
| 3 | Causal Narrative Builder (Stage 2) — provider-configurable LLM, template fallback. |
| 4 | Migration Decision Engine (Stage 3, Loop 4 gate #1) — Strategy A/B/C, human confirmation. |
| 5 | Codegen + Loop 1 self-correction (Stage 4) — template-anchored generation, generate → verify → inject failure → regenerate, capped at 3. |
| 6 | Verification Harness (Stage 5, Loop 3) — V1 static parse, V2 dbt compile, cheapest-first. |
| 7 | Dossier + PR delivery (Stage 6, Loop 4 gate #2) — full pipeline orchestration, dry-run-by-default PR preview. |
| 8 | Watch Mode + outcome log (Loop 5) — schema-snapshot diffing, autonomous detection with human-in-the-loop delivery. |
| 9 | Polish — this README, [`examples/`](examples/), [`skills/`](skills/), [`docs/demo-script.md`](docs/demo-script.md). |

V3 (shadow-schema execution), V4 (data parity), V5 (residue scan), and a fully automated merge-watch loop are explicitly out of scope for this submission (spec's Target/Stretch tiers) — see `docs/blast-radius-project-spec.md` §11 for the full scope ladder.

## The five loops

1. **Loop 1 — Self-correction** (`agent/loops/self_correction_loop.py`): generate → write → verify → inject failure evidence → regenerate, capped at 3 attempts, every attempt traced to `traces/`.
2. **Loop 2 — Bounded reasoning** (`agent/loops/reasoning_loop.py`): every DataHub MCP call is budgeted, depth-capped, and logged with a one-line rationale — no unbounded agentic wandering.
3. **Loop 3 — Verification Gauntlet** (`agent/verify/harness.py`): cheapest-first checks (V1 sqlglot parse, V2 dbt compile), stopping at the first failure.
4. **Loop 4 — Human confirmation gates**: migration-decision confirmation (`agent/decision/gate.py`) and PR delivery (`agent/dossier/pr.py`, dry-run by default) — a tool whose selling point is trust never claims a human signed off on something nobody was asked about.
5. **Loop 5 — Watch/outcome** (`agent/watch/`): schema-snapshot diffing detects changes that already happened and triggers the same pipeline, always with `auto_approve_decision=False, create_pr_live=False` — autonomous detection surfaces a proposed fix for review, it never acts unattended.

## CLI reference

Six entry points, each independently runnable (`--help` on any of them for full flags):

```bash
python -m agent.orchestrator.cli assess --table raw_customers --column cust_id
python -m agent.orchestrator.cli decide --table raw_customers --column cust_id --auto-approve
python -m agent.narrative.cli          --table raw_customers --column cust_id
python -m agent.codegen.cli            --table raw_customers --old-column cust_id --new-column customer_id
python -m agent.dossier.cli            --table raw_customers --old-column cust_id --new-column customer_id --auto-approve
python -m agent.watch.cli              --table raw_customers
```

`agent.dossier.cli` runs the full pipeline end to end and is the one most worth trying first. It never opens a real PR unless you explicitly pass `--create-pr` (see `agent/dossier/pr.py`'s module docstring before ever doing that). Every run saves the rendered dossier to `dossiers/<table>-<old>-to-<new>-<timestamp>.md` (override with `--output PATH`) — that's the durable, shareable artifact after a run, not just terminal output. Add `--write-to-datahub` to also persist it as a Document inside DataHub itself, linked to every affected asset.

## Repository layout

```
blast-radius/
├── agent/            # orchestrator, loops, assessment, decision, narrative, codegen, verify, dossier, watch
├── estate/           # dbt project, seeds, ingestion recipes, DataHub metadata emitters, golden outputs
├── traces/           # per-run reasoning + self-correction traces (gitignored, demo-run artifacts)
├── watch_state/      # watch-mode schema snapshots + outcome log (gitignored, demo-run artifacts)
├── dossiers/         # saved dossier markdown files from CLI runs (gitignored, demo-run artifacts)
├── examples/         # 3 complete runs spanning the decision spectrum: dossier + trace each
├── skills/           # packaged DataHub Skill (OSS contribution)
├── tests/            # unit tests (188 passing)
├── feedback-notes.md # running log of DataHub/MCP friction, for the Feedback Prize
└── docs/             # spec, kickoff guide, demo script
```

## Setup

See [`docs/blast-radius-kickoff-guide.md`](docs/blast-radius-kickoff-guide.md) for full environment setup (DataHub, MCP client, accounts). Quick start:

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env   # fill in credentials
docker compose up -d   # Postgres warehouse
datahub docker quickstart  # local DataHub instance
```

Then seed and ingest the demo estate (see the kickoff guide for the full sequence: `estate/seeds/`, `dbt run`, the two ingestion recipes, `estate/metadata/`), and run any CLI above.

### LLM provider

Narrative (Stage 2) and Codegen (Stage 4) go through a thin, provider-configurable client (`agent/narrative/llm_client.py`) — set `LLM_PROVIDER` in `.env` to `anthropic`, `openrouter`, `deepseek`, or `gemini`, plus the matching API key. With no key configured, both stages fall back to a deterministic template rather than failing — this is the default, fully-tested path today; adding a key requires no code changes.

## Testing

```bash
python -m pytest tests/ -v
```

184 tests, all fabricated-data unit tests except where a stage is genuinely integration-shaped (those are proven via live runs against the real DataHub/Postgres/dbt estate instead — see `examples/` for captured output).

## Provenance

See [`PROVENANCE.md`](PROVENANCE.md).
