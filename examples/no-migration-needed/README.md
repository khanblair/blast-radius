# no-migration-needed

Declaring a brand-new column (`loyalty_tier`) being added to `raw_customers` — a column that doesn't exist anywhere yet, so nothing has a real dependency on it.

**Decision:** ADDITIVE — "a new nullable column... cannot invalidate an existing consumer's query," so no patch is generated, just a documentation proposal.
**Real, live run** against the actual DataHub + Postgres + dbt estate — not fabricated.

**The interesting nuance this surfaces:** the assessment isn't a boring all-zero result. `fct_revenue` still shows up as an *affected* asset with a `SILENT_CORRUPTION` break mode — not because it reads `loyalty_tier` (nothing does yet), but because it independently does an un-firewalled `select *` from `dim_customers` (see `agent/assessment/break_mode.py`: `select_star_exposure` is a structural property of an asset's own SQL, assessed independently of whether the *current* declared change happens to break it). This is the two-axis break-mode design working as intended: "affected" and "needs a patch right now" are different questions, and the dossier is honest about both.

Reproduce:

```bash
source .venv/bin/activate && set -a; source .env; set +a
python -m agent.dossier.cli --table raw_customers --old-column loyalty_tier --new-column loyalty_tier_v2 --change-type add_column --auto-approve
```

Files:
- `dossier-output.txt` — full CLI output (no PR attempted — see the dossier's "No code change was needed" line).
- `trace-assessment.jsonl` — Loop 2's traced MCP calls for this run.
