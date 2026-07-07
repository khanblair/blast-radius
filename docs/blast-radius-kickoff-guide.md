# Blast Radius — Development Kickoff Guide

**Purpose:** everything needed to go from zero to a working DataHub instance + MCP connection + demo estate, so agent development can start on solid ground. This is Week 1 of the 35-day plan.

---

## 1. Machine Requirements

| Requirement | Spec |
|---|---|
| OS | macOS, Linux, or Windows (WSL2 recommended for Windows) |
| Docker | Docker Desktop (or Docker Engine + Compose v2 on Linux) |
| RAM allocated to Docker | **8 GB minimum** — DataHub's quickstart stack (GMS, frontend, Kafka, Elasticsearch, MySQL) is heavy |
| Disk | ~13 GB free |
| Python | **3.11** (targets both the DataHub CLI's 3.10+ requirement and the MCP server's pinned 3.11) |
| Package manager | `uv` recommended for the MCP server; `pip` fine everywhere else |
| Node.js | 20+ (only if you build a companion web UI later — not needed for MVP) |

---

## 2. Accounts & Credentials to Set Up Now

| Resource | What you need | Where |
|---|---|---|
| Devpost | Registered account, joined the hackathon | datahub.devpost.com |
| GitHub | A personal access token (fine-grained, repo scope) for the PR-automation bot identity | github.com/settings/tokens |
| Anthropic API | An API key for Claude (default LLM provider) | console.anthropic.com |
| OpenRouter API | An API key (unified access to many hosted models) | openrouter.ai/keys |
| DeepSeek API | An API key (DeepSeek-V3 / R1) | platform.deepseek.com |
| Google AI Studio (Gemini) | An API key for Gemini | aistudio.google.com/apikey |
| DataHub Slack | Join the community — useful for questions and visibility with judges | link on datahub.com |
| DataHub personal access token | Generated *after* DataHub is running (Step 4 below) | your local DataHub UI |

Blast Radius's LLM layer is **provider-configurable**, not hard-wired to one vendor. Anthropic Claude is the default; OpenRouter, DeepSeek, and Gemini are supported as alternates *for now* (selected via `LLM_PROVIDER` in `.env`), so narrative generation and codegen slot-fill can run against whichever model is cheapest or fastest to iterate on during development. You only need the key(s) for the provider(s) you actually intend to use.

Keep all of these in a local `.env` file (never committed — add to `.gitignore` immediately).

---

## 3. Step 1: Install the DataHub CLI

```bash
# macOS / Linux (simplest)
brew install datahub-project/tap/datahub

# Or via pip (any platform)
python3 -m pip install --upgrade pip wheel setuptools
python3 -m pip install --upgrade acryl-datahub
datahub version
```

Confirm it printed a version (expect something in the 1.2.x line or later).

---

## 4. Step 2: Bring Up DataHub Locally

```bash
datahub docker quickstart
```

This pulls and starts the full stack: GMS (metadata service), frontend, MySQL, Kafka, Elasticsearch, and the system-update job that provisions indexes. First run takes several minutes.

**Notes and gotchas:**
- Don't pass `--version latest` or `--version debug` — those tags aren't supported. Omit `--version` entirely to get the coordinated default.
- If Docker complains about resources, bump the Docker Desktop memory allocation to 8GB+ before retrying.
- Once healthy, the UI is at **http://localhost:9002**. Default login: `datahub` / `datahub`.
- To stop: `datahub docker quickstart --stop`. To fully wipe state and start clean: `datahub docker nuke`.
- If you want a working demo dataset immediately just to explore the UI (separate from our custom estate): `datahub init` then `datahub datapack load showcase-ecommerce`.

**Generate your Personal Access Token now** (needed for the MCP server and all ingestion): log into the UI → Settings → Access Tokens → Generate New Token. Save it to your `.env` as `DATAHUB_GMS_TOKEN`.

---

## 5. Step 3: Connect an MCP Client to DataHub

This is how you (and later, the agent) talk to DataHub through natural language / tool calls during development and exploration.

**Install and run via `uvx` (no separate install step needed):**

```bash
# Confirm uv/uvx is available
which uvx
```

**Claude Desktop config** — add to `claude_desktop_config.json`:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "datahub": {
      "command": "uvx",
      "args": ["mcp-server-datahub"],
      "env": {
        "DATAHUB_GMS_URL": "http://localhost:9002",
        "DATAHUB_GMS_TOKEN": "<your-datahub-token>",
        "TOOLS_IS_MUTATION_ENABLED": "true"
      }
    }
  }
}
```

**Important:** `TOOLS_IS_MUTATION_ENABLED=true` is what unlocks write-back (tags, ownership, proposals) — this is not optional for us, since the entire write-back/Proposals stage of Blast Radius depends on it.

If `uvx` fails with `ENOENT`, replace `"command": "uvx"` with the absolute path from `which uvx`.

Restart Claude Desktop, then sanity-check with a natural language prompt: *"Search DataHub for datasets related to 'orders' and show me their owners."* If it returns real results, the connection is live.

**Same config pattern works for Cursor** (`~/.cursor/mcp.json`) if that's your coding environment of choice — useful for agent development itself, not just exploration.

**Tools this server exposes** (the ones Blast Radius will call programmatically): search, list schema fields, get lineage (upstream/downstream, hop-controlled), get lineage path between two entities, get entity details by URN, and **get dataset queries** — real historical SQL against a dataset, which is exactly what feeds our usage-based severity scoring.

---

## 6. Step 4: Build the Demo Data Estate

This is the part that makes or breaks the demo, so budget real time here (2–3 days of Week 1).

**6.1 — Stand up a Postgres warehouse** (docker-compose service, separate from DataHub's own internal MySQL):
- Tables: `raw_customers`, `raw_orders`, `raw_payments` — seed with a few hundred synthetic rows (Faker library works well).

**6.2 — Build a small dbt project** on top of it:
- Staging models: `stg_customers` (write this one to explicitly `SELECT cust_id` — our designed `HARD_BREAK` case), `stg_orders`, `stg_payments`.
- Marts: `dim_customers`, `fct_orders`, `fct_revenue` — make `fct_revenue` reference upstream via `SELECT *` deliberately, so it becomes our `SILENT_CORRUPTION` showcase.
- A rough `jaffle-shop`-style structure is the well-trodden path here — many public dbt starter templates follow this pattern and are easy to adapt.

**6.3 — Represent the "dashboard" and pipeline layer:**
- A `revenue_dashboard` dataset/dashboard entity in DataHub depending on the marts (this can be a lightweight custom ingestion — it doesn't need a real BI tool behind it for the hackathon).
- Airflow DAG metadata representing orchestration of the dbt run (can be ingested via DataHub's Airflow ingestion source, or hand-authored metadata if standing up real Airflow is too heavy for the timeline — hand-authored is a reasonable Week 1 shortcut).

**6.4 — Ingest it all into DataHub:**
- Use DataHub's dbt ingestion source (YAML recipe) to pull in the dbt project's models, lineage, and docs.
- Use the Postgres/SQL ingestion source for the raw layer.
- Example recipe skeleton:
```yaml
source:
  type: postgres
  config:
    host_port: 'localhost:5432'
    database: warehouse
    username: '${PG_USER}'
    password: '${PG_PASSWORD}'
sink:
  type: datahub-rest
  config:
    server: 'http://localhost:8080'
```
Run with: `datahub ingest -c recipe.yml`

**6.5 — Enrich the estate** (do this via the DataHub UI or MCP mutation calls — good early practice for write-back):
- Assign **owners** per layer (so PR reviewer-tagging has real targets).
- Add **glossary terms** (`Customer ID`, `Net Revenue`).
- Add **documentation** on key datasets/columns.
- **Ingest sample queries** against the marts — either via DataHub's usage/query ingestion or by manually registering a handful of representative SQL queries, so usage-ranking in the severity matrix has real signal instead of defaulting to zero.

**6.6 — Capture golden outputs** for later V4 parity checks: run the pre-change dbt project once, export row counts and checksums for `fct_orders` and `fct_revenue`, and store them in `estate/golden/`. This is cheap to do now and expensive to reconstruct later.

---

## 7. Step 5: Scaffold the Agent Repo

```
blast-radius/
├── LICENSE                  # Apache 2.0 — add now, not later
├── README.md                # stub now, fill in as you build
├── .env.example              # documents required vars, no real secrets
├── .gitignore                 # .env, __pycache__, .venv, etc.
├── docker-compose.yml        # Postgres warehouse service (DataHub itself stays as `datahub docker quickstart`)
├── agent/
│   ├── orchestrator/
│   ├── loops/
│   ├── assessment/
│   ├── decision/
│   ├── narrative/
│   ├── codegen/
│   ├── verify/
│   └── dossier/
├── traces/
├── estate/
│   ├── dbt_project/
│   ├── seeds/
│   ├── ingestion_recipes/
│   └── golden/
├── examples/
├── skills/
└── feedback-notes.md          # start logging friction from hour one
```

**Set the LICENSE file first** — the rules require Apache 2.0 visible in the repo's About section, and it's a one-line mistake to forget until submission week.

**Python environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install anthropic openai google-genai sqlglot pygithub dbt-core dbt-postgres pyyaml python-dotenv rich
```

**Provenance discipline from day one:** every time you use an AI coding assistant, a template, or an open-source snippet, note it in a running `PROVENANCE.md` — this becomes the README's Provenance section later, and the rules require disclosure of pre-existing code.

---

## 8. Step 6: Verify the Full Loop End-to-End (Manually)

Before writing a line of agent orchestration code, do this by hand once, using Claude Desktop's MCP connection interactively:

1. Ask it to search for `raw_customers` and show its schema fields.
2. Ask it to get downstream lineage for `raw_customers.cust_id`.
3. Ask it to fetch queries against `fct_revenue`.
4. Ask it to propose a tag or description update on an asset (tests the mutation path).

If all four work, your entire data foundation — ingestion, lineage, ownership, query history, and write access — is confirmed live, and agent development can proceed on solid ground instead of debugging infrastructure and logic at the same time.

---

## 9. Week 1 Day-by-Day

| Day | Focus |
|---|---|
| 1 | CLI install, `datahub docker quickstart` healthy, UI login confirmed, PAT generated |
| 2 | MCP client connected (Claude Desktop or Cursor), manual tool exploration, GitHub PAT + LLM provider API key(s) ready (Anthropic default; OpenRouter/DeepSeek/Gemini as needed) |
| 3–4 | Postgres warehouse seeded, dbt project built (staging + marts, with the deliberate `HARD_BREAK`/`SILENT_CORRUPTION` cases designed in) |
| 5 | Ingestion recipes run, estate visible in DataHub UI with correct lineage |
| 6 | Enrichment pass: owners, glossary, docs, sample queries ingested; golden outputs captured |
| 7 | Repo scaffolded, LICENSE + Provenance discipline in place, manual end-to-end MCP verification (Step 8) passed, `feedback-notes.md` started |

**Exit criterion for Week 1:** you can open the DataHub UI, see the full estate with correct lineage from `raw_customers` down to `revenue_dashboard`, query it live through an MCP client, and have a clean repo skeleton with license and structure ready. Week 2 starts writing the Assessment Engine against this foundation.

---

## 10. Quick Reference — Key Commands

```bash
# Start / stop / reset DataHub
datahub docker quickstart
datahub docker quickstart --stop
datahub docker nuke

# Ingest metadata
datahub ingest -c path/to/recipe.yml

# Check CLI + server versions
datahub version --include-server

# Run the MCP server manually for debugging (outside a client)
uvx mcp-server-datahub
```

---

## 11. If Something Blocks You

- **DataHub won't come up healthy:** check Docker's allocated memory first (8GB+); `datahub docker check` reports cluster health.
- **MCP server not connecting:** confirm `DATAHUB_GMS_URL` and `DATAHUB_GMS_TOKEN` are correct and that DataHub is actually up; try the MCP Inspector for direct debugging outside your chat client.
- **Ingestion recipe fails:** validate credentials and connection strings first — most first-time failures are connectivity, not DataHub itself.
- **Genuinely stuck:** the DataHub Slack is active and monitored by people who may literally be adjacent to this hackathon's judges — a good, specific question there is also free goodwill.

Once Week 1's exit criterion is met, come back and we'll start on the Assessment Engine and Loop 2's bounded reasoning structure.
