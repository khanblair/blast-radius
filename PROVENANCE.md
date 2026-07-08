# Provenance

Running log of AI assistance, templates, and open-source snippets used while building Blast Radius, per the hackathon rules' disclosure requirement.

| Date | What | Source / Tool | Notes |
|---|---|---|---|
| 2026-07-07 | Repo scaffold, demo estate (Postgres warehouse, dbt project, DataHub ingestion/enrichment scripts), design + implementation planning | Claude Code (Anthropic), `claude-sonnet-5` | Phase 1 (Week 1 Foundation) built end-to-end with Claude Code, including DataHub Python SDK usage verified against `acryl-datahub` source and official docs. |
| 2026-07-07 | dbt project structure | Loosely modeled on the public `jaffle-shop` dbt starter pattern (per kickoff guide recommendation) | No code copied verbatim; naming/layer conventions only. |
| 2026-07-07 – 2026-07-08 | Phases 2-9: Assessment Engine, Narrative Builder, Decision Engine, Codegen + Loop 1 self-correction, Verification Harness, Dossier + PR delivery, Watch Mode, and all polish (README, examples/, skills/, demo script) | Claude Code (Anthropic), `claude-sonnet-5`, including parallel-subagent dispatch for independently-scoped phases (3+4, 5+6, 7+8), each reviewed, tested, and live-verified against the real DataHub/Postgres/dbt estate before integration | No code copied verbatim from external sources; DataHub MCP tool usage verified against `mcp-server-datahub`'s own source and live protocol calls, not documentation alone. |
