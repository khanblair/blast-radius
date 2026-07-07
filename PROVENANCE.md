# Provenance

Running log of AI assistance, templates, and open-source snippets used while building Blast Radius, per the hackathon rules' disclosure requirement.

| Date | What | Source / Tool | Notes |
|---|---|---|---|
| 2026-07-07 | Repo scaffold, demo estate (Postgres warehouse, dbt project, DataHub ingestion/enrichment scripts), design + implementation planning | Claude Code (Anthropic), `claude-sonnet-5` | Phase 1 (Week 1 Foundation) built end-to-end with Claude Code, including DataHub Python SDK usage verified against `acryl-datahub` source and official docs. |
| 2026-07-07 | dbt project structure | Loosely modeled on the public `jaffle-shop` dbt starter pattern (per kickoff guide recommendation) | No code copied verbatim; naming/layer conventions only. |
