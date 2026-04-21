"""Per-org Salesforce client powered by Playwright.

Each org runs in an isolated browser context (no cookie bleed) and
returns a list of dict rows per report. Selectors are centralized here
so Salesforce UI changes touch a single file.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from playwright.async_api import BrowserContext, async_playwright
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config_loader import OrgConfig, ReportConfig


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

    async def __aenter__(self) -> "SalesforceClient":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=not self.headed)
        self._context = await self._browser.new_context()
        await self._login()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _login(self) -> None:
        assert self._context is not None
        page = await self._context.new_page()
        logger.info(f"[{self.org.name}] logging in")
        await page.goto(self.org.login_url)
        await page.fill("#username", self.org.username)
        await page.fill("#password", self.org.password)
        await page.click("#Login")
        # TODO: handle MFA / verification-code flows.
        await page.wait_for_load_state("networkidle")
        await page.close()

    async def fetch_report(self, report: ReportConfig) -> ReportResult:
        assert self._context is not None

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
        # TODO: replace with real Salesforce report navigation + CSV export.
        # Placeholder stub so the scaffolding runs end-to-end while logic is built.
        assert self._context is not None
        _ = await self._context.new_page()
        return []
