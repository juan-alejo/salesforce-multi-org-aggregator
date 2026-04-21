"""Per-org Salesforce client powered by Playwright.

Each org runs in an isolated browser context (no cookie bleed) and
returns a list of dict rows per report. Selectors are centralized here
so Salesforce UI changes touch a single file.

Session reuse: on first run we log in interactively (MFA email code
prompt is typed by the user). The authenticated browser state + the
org's instance URL are persisted under data/sessions/<org>.*. On
subsequent runs we skip login entirely — no more MFA challenges until
Salesforce invalidates the session.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from playwright.async_api import BrowserContext, Page, async_playwright
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config_loader import OrgConfig, ReportConfig

# Locale-agnostic patterns — extend as new locales come in.
_EXPORT_MENU = re.compile(r"^(Exportar|Export)$", re.IGNORECASE)
_DETAILS_ONLY = re.compile(r"(Solo detalles|Details Only)", re.IGNORECASE)
_EXPORT_BUTTON = re.compile(r"^(Exportar|Export)$", re.IGNORECASE)
_MORE_ACTIONS = re.compile(r"(Más acciones|More actions)", re.IGNORECASE)
_CSV_OPTION = re.compile(r"(Valores separados por comas|Comma Separated Values|CSV)", re.IGNORECASE)
_UTF8_OPTION = re.compile(r"UTF-?8", re.IGNORECASE)
_REPORT_LOADED_BTN = "button:has-text('Modificar'), button:has-text('Edit')"

_LIGHTNING_URL_RE = re.compile(r"https://[^/]+\.lightning\.force\.com/")
_SESSIONS_DIR = Path("data/sessions")


@dataclass
class ReportResult:
    org: str
    report_name: str
    rows: list[dict]


class SalesforceClient:
    """One instance per org. Use as an async context manager."""

    def __init__(self, org: OrgConfig, *, headed: bool = False) -> None:
        self.org = org
        self.headed = headed
        self._pw = None
        self._browser = None
        self._context: BrowserContext | None = None
        self._base_url: str | None = None

    @property
    def _state_path(self) -> Path:
        return _SESSIONS_DIR / f"{self.org.name}.state.json"

    @property
    def _meta_path(self) -> Path:
        return _SESSIONS_DIR / f"{self.org.name}.meta.json"

    async def __aenter__(self) -> "SalesforceClient":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=not self.headed)

        if self._state_path.exists() and self._meta_path.exists():
            meta = json.loads(self._meta_path.read_text())
            self._base_url = meta.get("base_url")
            logger.info(f"[{self.org.name}] reusing saved session ({self._base_url})")
            self._context = await self._browser.new_context(
                accept_downloads=True, storage_state=str(self._state_path)
            )
            if not await self._session_is_valid():
                logger.warning(f"[{self.org.name}] stored session expired — re-logging in")
                await self._context.close()
                await self._fresh_login_and_save()
        else:
            await self._fresh_login_and_save()

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _session_is_valid(self) -> bool:
        """Hit the org's Lightning home. If still authenticated we stay on
        *.lightning.force.com; otherwise Salesforce redirects us to the login page."""
        assert self._context is not None
        assert self._base_url is not None
        page = await self._context.new_page()
        try:
            await page.goto(f"{self._base_url}/lightning", timeout=30_000)
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            return bool(_LIGHTNING_URL_RE.match(page.url))
        finally:
            await page.close()

    async def _fresh_login_and_save(self) -> None:
        assert self._browser is not None
        self._context = await self._browser.new_context(accept_downloads=True)
        await self._login_interactive()

        _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(self._state_path))
        self._meta_path.write_text(json.dumps({"base_url": self._base_url}, indent=2))
        logger.info(f"[{self.org.name}] session saved")

    async def _login_interactive(self) -> None:
        """Types user/pass automatically. If Salesforce shows an MFA challenge,
        waits for the user to type the code in the visible browser window."""
        assert self._context is not None
        page = await self._context.new_page()
        logger.info(f"[{self.org.name}] logging in at {self.org.login_url}")

        await page.goto(self.org.login_url)
        await page.fill("#username", self.org.username)
        await page.fill("#password", self.org.password)
        await page.click("#Login")

        logger.info(
            f"[{self.org.name}] waiting up to 5 minutes for login to reach Lightning "
            "(complete MFA in the browser window if prompted)"
        )
        await page.wait_for_url(_LIGHTNING_URL_RE, timeout=300_000)
        await page.wait_for_load_state("domcontentloaded")

        parsed = urlparse(page.url)
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        logger.info(f"[{self.org.name}] logged in — instance: {self._base_url}")
        await page.close()

    async def fetch_report(self, report: ReportConfig) -> ReportResult:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=20),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                rows = await self._fetch_report_once(report)
                logger.info(
                    f"[{self.org.name}] fetched '{report.name}' ({len(rows)} rows)"
                )
                return ReportResult(org=self.org.name, report_name=report.name, rows=rows)

        raise RuntimeError("unreachable")

    async def _fetch_report_once(self, report: ReportConfig) -> list[dict]:
        assert self._context is not None
        assert self._base_url is not None

        page = await self._context.new_page()
        try:
            report_url = f"{self._base_url}/lightning/r/Report/{report.id}/view"
            logger.debug(f"[{self.org.name}] navigating to {report_url}")
            await page.goto(report_url)

            # The report UI is in a single iframe, but the dropdown menu and the
            # export dialog are portalled to the top-level document.
            frame = page.frame_locator("iframe").first
            await self._wait_for_report_loaded(frame)

            await self._open_more_actions(frame)
            await self._click_export_menu_item(frame)  # menu lives in iframe
            await self._select_details_only(page)      # dialog lives in main frame
            await self._select_csv_format(page)
            await self._select_utf8_encoding(page)

            async with page.expect_download(timeout=60_000) as download_info:
                await page.locator(
                    "button:has-text('Exportar'), button:has-text('Export')"
                ).last.click()
            download = await download_info.value

            tmp_path = Path(await download.path())
            logger.debug(f"[{self.org.name}] downloaded to {tmp_path}")
            return _parse_csv(tmp_path)
        except Exception:
            debug_dir = Path("data/debug")
            debug_dir.mkdir(parents=True, exist_ok=True)
            shot = debug_dir / f"{self.org.name}_{report.id}.png"
            try:
                await page.screenshot(path=str(shot), full_page=True)
                logger.error(f"[{self.org.name}] debug screenshot saved to {shot}")
            except Exception:
                pass
            raise
        finally:
            await page.close()

    async def _wait_for_report_loaded(self, frame) -> None:
        await frame.locator(_REPORT_LOADED_BTN).first.wait_for(timeout=60_000)

    async def _open_more_actions(self, frame) -> None:
        # "Más acciones" / "More actions" — the ▼ split-button next to Edit.
        await frame.locator(
            "button:has-text('Más acciones'), button:has-text('More actions')"
        ).first.click(timeout=10_000)

    async def _click_export_menu_item(self, frame) -> None:
        await frame.get_by_role("menuitem", name=_EXPORT_MENU).click(timeout=10_000)

    async def _select_details_only(self, page: Page) -> None:
        await page.get_by_text(_DETAILS_ONLY).first.click(timeout=10_000)

    async def _select_csv_format(self, page: Page) -> None:
        # The dialog can contain up to 2 selects (format, and conditionally encoding).
        # Find the one whose options include a CSV variant — that's the format select.
        await self._pick_from_select(page, _CSV_OPTION, "CSV")

    async def _select_utf8_encoding(self, page: Page) -> None:
        # After CSV is chosen, an encoding select appears — default is ISO-8859-1.
        # Switch to UTF-8 so the downloaded bytes decode cleanly.
        await self._pick_from_select(page, _UTF8_OPTION, "UTF-8")

    async def _pick_from_select(self, page: Page, pattern: re.Pattern, label: str) -> None:
        selects = page.locator("select")
        count = await selects.count()
        for i in range(count):
            sel = selects.nth(i)
            options = await sel.locator("option").all_text_contents()
            for opt in options:
                if pattern.search(opt):
                    await sel.select_option(label=opt)
                    return
        raise RuntimeError(f"no {label} option found in any export dropdown")


def _parse_csv(path: Path) -> list[dict]:
    """Salesforce report exports use UTF-8 (with BOM) and a delimiter that
    depends on the org's locale — Spanish locales ship ';' while English
    ships ','. Sniff the first line and pick whichever the file actually uses."""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))
