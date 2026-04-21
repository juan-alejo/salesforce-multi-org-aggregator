# Salesforce Multi-Org Report Aggregator

> Automated report extraction and consolidation across dozens of Salesforce orgs — in one command.

[![CI](https://github.com/juan-alejo/salesforce-multi-org-aggregator/actions/workflows/ci.yml/badge.svg)](https://github.com/juan-alejo/salesforce-multi-org-aggregator/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Playwright](https://img.shields.io/badge/browser-Playwright%20Chromium-45ba4b)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow)

Managing reports across multiple Salesforce orgs is painful. Each org has its own credentials, each team exports the same metrics manually every week, and "just give me the consolidated view" turns into a full day of copy-paste.

This tool solves that. Point it at a YAML file listing your orgs, tell it which reports to fetch, and it returns a single consolidated dataset — CSV, SQLite, or Excel. Runs headless, handles retries, can be scheduled.

## Example output

One command, two orgs, one consolidated CSV:

```
$ python -m src.main --config config/orgs.yaml --output out/weekly
[Prod-US] reusing saved session
[Staging-EU] reusing saved session
[Prod-US] fetched 'Weekly Pipeline' (142 rows)
[Staging-EU] fetched 'Weekly Pipeline' (89 rows)
aggregated 231 row(s) across 2 org(s)
wrote 231 row(s) to out/weekly.csv
```

```csv
_org,_report,Account Owner,Account Name,Billing State,Type,Rating
Prod-US,Weekly Pipeline,Jane Doe,Edge Communications,TX,Customer - Direct,Hot
Prod-US,Weekly Pipeline,John Roe,"United Oil & Gas, UK",UK,Customer - Direct,Warm
Staging-EU,Weekly Pipeline,Alex Lee,GenePoint,CA,Customer - Channel,Cold
...
```

## Features

- **Multi-org by config** — add a new org by appending to `config/orgs.yaml`. No code changes.
- **Session persistence** — log in interactively once (MFA and all), the browser state is saved and reused. Subsequent runs skip login entirely.
- **Headless browser automation** — Playwright (Chromium) with auto-wait and robust selectors.
- **Parallel execution** — fetch N orgs concurrently with a configurable concurrency cap.
- **Retry + backoff** — transient errors and rate limits handled automatically (Tenacity).
- **Locale-aware** — works against orgs in English, Spanish, and other locales without code changes.
- **Multiple output formats** — CSV, SQLite, or Excel (`.xlsx`).
- **Structured logging** — JSON-friendly logs per run (Loguru), easy to ship to Datadog/Grafana.
- **Scheduler-friendly** — exit codes + idempotent output paths play nice with cron / Task Scheduler / GitHub Actions.

## Tech stack

- Python 3.11+
- [Playwright](https://playwright.dev/python/) for browser automation
- [Pydantic](https://docs.pydantic.dev/) for config validation
- [Tenacity](https://tenacity.readthedocs.io/) for retries
- [Loguru](https://loguru.readthedocs.io/) for structured logs
- `pytest` + `ruff` for testing and linting

## Quick start

```bash
# 1. Install deps
pip install -r requirements.txt        # runtime only
pip install -r requirements-dev.txt    # adds pytest + ruff
playwright install chromium

# 2. Copy the example config and fill in your orgs
cp config/orgs.yaml.example config/orgs.yaml
cp .env.example .env
# edit both files

# 3. First run — a Chromium window opens so you can complete MFA once
python -m src.main --config config/orgs.yaml --headed

# 4. Subsequent runs are fully headless, no MFA
python -m src.main --config config/orgs.yaml
```

## Configuration

Each org is an entry in `config/orgs.yaml`:

```yaml
concurrency: 4          # how many orgs to process in parallel
output_format: csv      # csv | sqlite | xlsx
output_path: out/report # extension appended automatically

orgs:
  - name: Prod-US
    login_url: https://login.salesforce.com
    username_env: SF_PROD_US_USER
    password_env: SF_PROD_US_PASS
    reports:
      - id: "00O1x0000012345"
        name: Weekly Pipeline
  - name: Staging-EU
    login_url: https://test.salesforce.com
    username_env: SF_STAGE_EU_USER
    password_env: SF_STAGE_EU_PASS
    reports:
      - id: "00O1x0000067890"
        name: Weekly Pipeline
```

Credentials live in environment variables (see `.env.example`), never in the YAML. Recommended: use a secrets manager (AWS Secrets Manager, 1Password CLI, etc.) in production.

## Architecture

```
                 ┌──────────────────────┐
                 │   orgs.yaml (config) │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │    ConfigLoader      │  ← Pydantic validation
                 └──────────┬───────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
   ┌──────▼──────┐   ┌──────▼──────┐    ┌─────▼───────┐
   │  OrgWorker  │   │  OrgWorker  │... │  OrgWorker  │  ← asyncio.gather, bounded
   │ (Playwright)│   │ (Playwright)│    │ (Playwright)│
   └──────┬──────┘   └──────┬──────┘    └──────┬──────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
                   ┌────────▼────────┐
                   │   Aggregator    │  ← merges, tags rows with org/report
                   └────────┬────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         ┌────▼───┐    ┌────▼───┐    ┌───▼────┐
         │  CSV   │    │ SQLite │    │  XLSX  │
         └────────┘    └────────┘    └────────┘
```

## Real-world challenges solved

Building this against live Salesforce orgs surfaced a handful of UI and protocol quirks that naive automation trips over. Documenting them here because they're the interesting part — not "pip install and it works," but "here's why the straightforward approach *doesn't* work."

### 1. Lightning's iframe + shadow-DOM split

The report UI lives inside an `<iframe>`, but the action menu it opens **portals its contents into the top-level document**. Classic Playwright locators scoped to `page` miss the iframe; locators scoped to `page.frame_locator("iframe")` miss the portalled menu.

The working approach: route each interaction to the frame it actually renders in.

```python
frame = page.frame_locator("iframe").first
await frame.locator(...)                # report body + dropdown trigger
await page.get_by_text(...)             # portalled menu + dialog
```

Discovered by running JS in the page to enumerate `document` + all frames and see where a given `textContent` actually lives.

### 2. Email-MFA on every new browser fingerprint

Playwright's Chromium is a fresh install with zero saved cookies — every run looks like a "new device" to Salesforce, triggering an email verification challenge. You can't script past it: the code lands in your inbox.

Solution: first run is **interactive** with a visible browser. User types the MFA code once; the authenticated `storage_state` is persisted to `data/sessions/<org>.state.json`. Subsequent runs reuse the cookies and skip the challenge entirely. The meta file alongside it records the org's instance URL so we can probe it on startup to confirm the session is still live.

### 3. Locale-dependent CSV delimiter

Spanish-locale orgs export CSVs delimited by `;` (because `,` is the decimal separator). English-locale orgs use `,`. A hard-coded delimiter silently produces a single-column output where every row is one giant string.

Fix: `csv.Sniffer` inspects the first 4KB of the file and picks the correct dialect automatically.

```python
dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
```

### 4. Default export encoding is ISO-8859-1, not UTF-8

The export dialog's encoding dropdown defaults to Latin-1. The downloaded bytes have a 0xDA in position 1 that decodes with `UnicodeDecodeError` under `utf-8`. The dropdown only appears **after** CSV is selected as the format — a stateful two-step interaction.

Fix: explicitly select the `Unicode (UTF-8)` option after switching format. Both select boxes are enumerated and matched by regex on their option labels, so the same code path works across UI revisions.

### 5. Locale-agnostic selectors

The same button reads "Modificar" in a Spanish org and "Edit" in an English one. Relying on text-match-by-equality locks the script to one locale. All interactions go through regex-compiled name patterns so a single deployment handles both — and new locales are one line apiece.

```python
_EXPORT_MENU = re.compile(r"^(Exportar|Export)$", re.IGNORECASE)
```

## Design decisions

- **Playwright over Selenium** — faster, auto-waits on network/DOM, better error messages, first-class async, no WebDriver version headaches.
- **YAML over CLI flags** — a team managing 15+ orgs needs diffable, reviewable config, not a 300-char command.
- **Env vars for creds** — YAML gets committed (sanitized); secrets never do. Storage-state files live under a gitignored `data/` tree and are treated as password-equivalent.
- **Asyncio with bounded concurrency** — avoids hammering Salesforce and tripping rate limits.
- **Per-org isolated browser context** — no cookie or session bleed between orgs.
- **Debug screenshots on failure** — `_fetch_report_once` dumps a full-page PNG to `data/debug/` whenever anything in the export flow fails. Invaluable when a new Salesforce UI rev shifts a selector.

## Testing

```bash
pytest              # unit tests — config validation, CSV parser, output writers
ruff check .        # lint
```

The browser flow is deliberately excluded from CI (requires live Salesforce orgs and interactive MFA). Run it manually against a Dev Edition org — signup at [developer.salesforce.com](https://developer.salesforce.com/signup).

## Roadmap

- [x] Report export via Lightning UI (CSV, XLSX, SQLite outputs)
- [x] Session persistence — no MFA on subsequent runs
- [x] Locale-aware selectors (Spanish + English)
- [x] Sniff-based delimiter detection
- [ ] Salesforce REST API path as a faster alternative when Connected App access is available
- [ ] Scheduled runs via GitHub Actions cron with secrets
- [ ] Webhook notifications on run completion

## License

MIT — see [LICENSE](./LICENSE).
