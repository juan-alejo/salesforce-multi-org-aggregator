"""Orchestrates per-org workers with bounded concurrency and merges results."""

from __future__ import annotations

import asyncio

from loguru import logger

from .config_loader import AppConfig, OrgConfig
from .salesforce_client import ReportResult, SalesforceClient


async def run(config: AppConfig, *, headed: bool = False) -> list[ReportResult]:
    semaphore = asyncio.Semaphore(config.concurrency)
    tasks = [_run_org(org, semaphore, headed=headed) for org in config.orgs]

    org_results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[ReportResult] = []
    for org, result in zip(config.orgs, org_results):
        if isinstance(result, Exception):
            logger.error(f"[{org.name}] failed: {result}")
            continue
        merged.extend(result)

    logger.info(f"aggregated {len(merged)} report(s) across {len(config.orgs)} org(s)")
    return merged


async def _run_org(
    org: OrgConfig, semaphore: asyncio.Semaphore, *, headed: bool
) -> list[ReportResult]:
    async with semaphore:
        async with SalesforceClient(org, headed=headed) as client:
            return [await client.fetch_report(r) for r in org.reports]
