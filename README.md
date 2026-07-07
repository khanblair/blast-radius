# Blast Radius

**A schema-change intelligence and migration copilot built on DataHub.**

Blast Radius explains what broke, why, and how; decides whether a migration is even needed; generates the fix and self-corrects until it verifiably works; delivers it as a PR your team would actually merge; and confirms the migration succeeded after it lands.

**Hackathon:** Build with DataHub: The Agent Hackathon
**Challenge category:** Metadata-Aware Code Generation & Development (Category 2)
**Built on:** DataHub Core (open-source) + the DataHub MCP Server
**License:** Apache 2.0

Full design: [`docs/blast-radius-project-spec.md`](docs/blast-radius-project-spec.md). Kickoff/setup guide: [`docs/blast-radius-kickoff-guide.md`](docs/blast-radius-kickoff-guide.md).

## Status

**Phase 1 — Week 1 Foundation** in progress: repo scaffold, local DataHub instance, Postgres warehouse, dbt demo estate (with deliberate `HARD_BREAK` and `SILENT_CORRUPTION` cases), ingestion, enrichment, golden outputs. See [`docs/superpowers/specs/2026-07-07-phase1-foundation-design.md`](docs/superpowers/specs/2026-07-07-phase1-foundation-design.md).

Agent stages (Assessment, Decision, Narrative, Codegen, Verify, Dossier, Loops) ship in subsequent phases once this foundation is live.

## Repository layout

```
blast-radius/
├── agent/            # orchestrator, loops, assessment, decision, narrative, codegen, verify, dossier
├── estate/           # dbt project, seeds, ingestion recipes, DataHub metadata emitters, golden outputs
├── traces/           # per-run reasoning + self-correction traces
├── examples/         # complete runs: dossier + generated PR + trace
├── skills/           # packaged DataHub Skill (OSS contribution)
├── tests/            # unit tests
└── docs/             # spec, kickoff guide, design/plan docs
```

## Setup

See [`docs/blast-radius-kickoff-guide.md`](docs/blast-radius-kickoff-guide.md) for full environment setup (DataHub, MCP client, accounts). Quick start:

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env   # fill in credentials
```

## Provenance

See [`PROVENANCE.md`](PROVENANCE.md).
