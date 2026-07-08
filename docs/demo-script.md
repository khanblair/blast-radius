# Demo Script (< 3 min)

Runnable version of the spec's demo script (`blast-radius-project-spec.md` §9). Every command below is real and has been run against the live estate; the timings are targets for recording, not measured.

**Before recording:** `docker compose up -d`, `datahub docker quickstart` (if not already running), `source .venv/bin/activate && set -a; source .env; set +a`. Confirm `docker ps` shows the DataHub containers and `blast_radius_warehouse` healthy, and `curl -s localhost:8080/health` returns 200.

---

## 0:00–0:15 — The problem

Show a lineage graph in the DataHub UI (`http://localhost:9002`) for `raw_customers` → `stg_customers` → `dim_customers`/`fct_orders` → `fct_revenue`. State the category and tooling: *Metadata-Aware Code Generation & Development, built on DataHub Core via the DataHub MCP Server.*

## 0:15–0:35 — The break, caught unprompted

This is the one scene that requires a **real, deliberate mutation** — everything else in this script is read-only or writes to a temp copy. Do this once, right before recording, not as part of routine development:

```bash
# 1. Apply the real rename to the warehouse
psql "postgresql://$PG_USER:$PG_PASSWORD@$PG_HOST:$PG_PORT/$PG_DATABASE" \
  -c 'ALTER TABLE raw_customers RENAME COLUMN cust_id TO customer_id;'

# 2. Re-ingest so DataHub reflects the new schema
datahub ingest -c estate/ingestion_recipes/postgres_to_datahub.yml
cd estate/dbt_project && dbt run --select stg_customers && cd -
datahub ingest -c estate/ingestion_recipes/dbt_to_datahub.yml

# 3. Watch mode catches it -- unprompted
python -m agent.watch.cli --table raw_customers
```

The watch CLI's second-ever run against this table (the first captured the pre-rename baseline — see `watch_state/raw_customers.json` from any earlier `--once` run) now diffs against a real, changed live schema and reports a `possible_rename` `DetectedChange` instead of "zero changes." **This is the only step in the whole system that mutates the shared Postgres/DataHub state — every other command below is either read-only against the live estate or writes to a disposable temp copy.**

Reverting after recording: `ALTER TABLE raw_customers RENAME COLUMN customer_id TO cust_id;`, re-run both ingestion commands above, then re-run `dbt run --select stg_customers` — this restores every other example/demo command in this repo to its documented behavior.

## 0:35–1:10 — The intelligence

```bash
python -m agent.orchestrator.cli assess --table raw_customers --column cust_id
```

Narrate the severity matrix on screen: "3 hard breaks, 1 silent-corruption risk, confirmed safe elsewhere." Then:

```bash
python -m agent.narrative.cli --table raw_customers --column cust_id
```

Read one causal narrative aloud with its file:line evidence (`stg_customers.sql:4: cust_id,`). Then:

```bash
python -m agent.orchestrator.cli decide --table raw_customers --column cust_id --auto-approve
```

Strategy B (bridge migration) on screen, with rationale and the rejected A/C alternatives shown.

## 1:10–1:45 — The self-correction moment ⭐

```bash
python -m agent.codegen.cli --table raw_customers --old-column cust_id --new-column customer_id
```

With no LLM key configured this passes on attempt 1 (template fallback) — **configure a real provider key first if you want a genuine multi-attempt recording** (any of `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`/`DEEPSEEK_API_KEY`/`GEMINI_API_KEY` in `.env`, matching `LLM_PROVIDER`). Show the trace live:

```bash
cat traces/selfcorrect-*.jsonl | tail -1 | python -m json.tool
```

Narrate whichever attempt failed: `[V2_COMPILE] FAIL -- ... -> injected as failure_evidence -> regenerated -> passed`.

## 1:45–2:20 — The money shot

```bash
python -m agent.dossier.cli --table raw_customers --old-column cust_id --new-column customer_id --auto-approve
```

This is the dossier — all 5 sections in one document, screenshot-gold. **Do not pass `--create-pr` unless you have deliberately decided to open a real PR against a real repo you control** (see `agent/dossier/pr.py`'s module docstring for exactly what that flag does). For the recording, the dry-run preview (branch name, diff, dossier-as-PR-body) is the intended shot — cut to the DataHub UI showing the affected assets.

## 2:20–2:40 — The loop closes

Manual for this submission (spec's scope ladder marks fully-automated merge-watch as Stretch): narrate that a merged PR would produce an Outcome Record via `agent/watch/outcome.py`'s `record_outcome`, closing Loop 5. If a real PR was opened and merged, show `agent.watch.outcome.read_outcomes()`'s output.

## 2:40–3:00 — Architecture + close

Flash the architecture diagram (`docs/blast-radius-project-spec.md` §7), flash `examples/` (three dossiers spanning the decision spectrum — BREAKING/B, ADDITIVE, BREAKING/C-defer), mention the packaged `skills/datahub-impact-analysis/` as the OSS contribution, one-liner close.

---

## Full command reference

Every CLI supports `--help`. Six entry points:

| Command | Purpose |
|---|---|
| `python -m agent.orchestrator.cli assess --table T --column C` | Impact assessment only (Stage 1). |
| `python -m agent.orchestrator.cli decide --table T --column C [--auto-approve]` | + Migration Decision (Stage 3, Loop 4 gate #1). |
| `python -m agent.narrative.cli --table T --column C` | Causal narratives only (Stage 2). |
| `python -m agent.codegen.cli --table T --old-column C --new-column C2` | Codegen + Loop 1 self-correction only (Stage 4). |
| `python -m agent.dossier.cli --table T --old-column C --new-column C2 [--auto-approve] [--create-pr]` | The full pipeline end to end (Stages 0–6). |
| `python -m agent.watch.cli --table T` | One watch-mode cycle: capture, diff, trigger (Loop 5). |
