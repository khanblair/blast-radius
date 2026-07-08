# simple-rename

The canonical demo scenario: `raw_customers.cust_id` is renamed to `customer_id`.

**Decision:** BREAKING — Strategy B (bridge migration), because `fct_revenue` is dashboard-exposed.
**Self-correction:** passed on attempt 1 (both V1_STATIC and V2_COMPILE).
**Real, live run** against the actual DataHub + Postgres + dbt estate — not fabricated.

Reproduce:

```bash
source .venv/bin/activate && set -a; source .env; set +a
python -m agent.dossier.cli --table raw_customers --old-column cust_id --new-column customer_id --auto-approve
```

Files:
- `dossier-output.txt` — full CLI output (dry-run PR preview, which embeds the dossier as the would-be PR body).
- `trace-assessment.jsonl` — Loop 2's traced MCP calls (search, column-scoped + broad lineage, dashboard upstream, usage queries) for this run.
- `trace-self-correction.jsonl` — Loop 1's traced attempt (generate → write → verify → pass).
