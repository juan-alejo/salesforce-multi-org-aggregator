# Salesforce Multi-Org Report Aggregator

> Automated report extraction and consolidation across dozens of Salesforce orgs — in one command.

Managing reports across multiple Salesforce orgs is painful. Each org has its own credentials, each team exports the same metrics manually every week, and "just give me the consolidated view" turns into a full day of copy-paste.

This tool solves that. Point it at a YAML file listing your orgs, tell it which reports to fetch, and it returns a single consolidated dataset — CSV, SQLite, or Excel. Runs headless, handles retries, can be scheduled.

## Features

- **Multi-org by config** — add a new org by appending to `config/orgs.yaml`. No code changes.
- **Headless browser automation** — Playwright (Chromium) with auto-wait and robust selectors.
- **Parallel execution** — fetch N orgs concurrently with a configurable concurrency cap.
- **Retry + backoff** — transient errors and rate limits handled automatically.
- **Multiple output formats** — CSV, SQLite, or Excel (`.xlsx`).
- **Structured logging** — JSON logs per run, easy to ship to Datadog/Grafana.
- **Scheduler-friendly** — exit codes + idempotent output paths play nice with cron / Task Scheduler / GitHub Actions.

## Tech stack

- Python 3.11+
- [Playwright](https://playwright.dev/python/) for browser automation
- [Pydantic](https://docs.pydantic.dev/) for config validation
- [Tenacity](https://tenacity.readthedocs.io/) for retries
- [Loguru](https://loguru.readthedocs.io/) for structured logs
- `pytest` + `pytest-asyncio` for testing

## Quick start

```bash
# 1. Install deps
pip install -r requirements.txt         # runtime only
pip install -r requirements-dev.txt     # adds pytest + ruff
playwright install chromium

# 2. Copy the example config and fill in your orgs
cp config/orgs.yaml.example config/orgs.yaml

# 3. Run
python -m src.main --config config/orgs.yaml --output out/report.csv
```

## Configuration

Each org is an entry in `config/orgs.yaml`:

```yaml
orgs:
  - name: "Prod-US"
    login_url: "https://login.salesforce.com"
    username_env: "SF_PROD_US_USER"
    password_env: "SF_PROD_US_PASS"
    reports:
      - id: "00O1x0000012345"
        name: "Weekly Pipeline"
  - name: "Staging-EU"
    login_url: "https://test.salesforce.com"
    username_env: "SF_STAGE_EU_USER"
    password_env: "SF_STAGE_EU_PASS"
    reports:
      - id: "00O1x0000067890"
        name: "Weekly Pipeline"

concurrency: 4
output_format: "csv"  # csv | sqlite | xlsx
```

Credentials live in environment variables (see `.env.example`), never in the YAML. Recommended: use a secrets manager (AWS Secrets Manager, 1Password CLI, etc.) in production.

## Architecture

```
                 ┌──────────────────────┐
                 │   orgs.yaml (config) │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │  ConfigLoader        │  ← Pydantic validation
                 └──────────┬───────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
   ┌──────▼─────┐   ┌──────▼─────┐    ┌──────▼─────┐
   │ OrgWorker  │   │ OrgWorker  │... │ OrgWorker  │  ← asyncio.gather with semaphore
   │ (Playwrt)  │   │ (Playwrt)  │    │ (Playwrt)  │
   └──────┬─────┘   └──────┬─────┘    └──────┬─────┘
          │                │                 │
          └────────────────┼─────────────────┘
                           │
                  ┌────────▼────────┐
                  │   Aggregator    │  ← merges, deduplicates, tags with org name
                  └────────┬────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────▼───┐   ┌────▼───┐   ┌───▼────┐
         │  CSV   │   │ SQLite │   │  XLSX  │
         └────────┘   └────────┘   └────────┘
```

## Design decisions

- **Playwright over Selenium** — faster, auto-waits on network/DOM, better error messages, first-class async.
- **YAML over CLI flags** — a team managing 15+ orgs needs diffable, reviewable config, not a 300-char command.
- **Env vars for creds** — YAML gets committed (sanitized); secrets never do.
- **Asyncio with bounded concurrency** — avoids hammering Salesforce and tripping rate limits.
- **Per-org isolated browser context** — no cookie/session bleed between orgs.

## Project status

Work in progress — check the issues tab for the roadmap.

## License

MIT
