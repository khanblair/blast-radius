# Examples

Three captured runs, chosen to span the judgment spectrum the Decision Engine actually has to navigate — not three sizes of the same rename. Each folder has a `dossier-output.txt` (what the CLI printed) and, where the run is live, the trace file(s) it wrote to `traces/`.

| Example | Decision | What it shows |
|---|---|---|
| [`simple-rename/`](simple-rename/) | **BREAKING — Strategy B** | The canonical demo scenario: `raw_customers.cust_id` → `customer_id`. 3 hard breaks, 1 dashboard-exposed, self-correction passes on attempt 1, dry-run PR preview. Real, live run against the actual DataHub/Postgres/dbt estate. |
| [`no-migration-needed/`](no-migration-needed/) | **ADDITIVE** | Declaring a brand-new column on `raw_customers`. Zero hard breaks — but `fct_revenue`'s un-firewalled `select *` still gets flagged as an independent, pre-existing silent-corruption risk. Shows "affected ≠ needs patching." Real, live run. |
| [`large-blast-defer/`](large-blast-defer/) | **BREAKING — Strategy C (defer)** | The Decision Engine recommending *against* an immediate fix. This project's own demo estate is deliberately small and never naturally trips the defer thresholds (>5 hard breaks or hop ≥ 4) — so this one is a **labeled synthetic input** run through the real, unmodified decision/rendering code. See that folder's README for exactly what's real vs. fabricated. |

Every dossier here was produced by `agent/dossier/renderer.py`'s real `render_dossier()` — nothing in these three files was hand-written markdown.
