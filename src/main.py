"""CLI entry point.

Usage:
    python -m src.main --config config/orgs.yaml
    python -m src.main --config config/orgs.yaml --output out/weekly --format xlsx --headed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from . import aggregator
from .config_loader import load_config
from .output_writers import write


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Salesforce multi-org report aggregator")
    parser.add_argument("--config", required=True, help="Path to orgs.yaml")
    parser.add_argument("--output", help="Override output_path (no extension)")
    parser.add_argument(
        "--format", choices=["csv", "sqlite", "xlsx"], help="Override output_format"
    )
    parser.add_argument("--headed", action="store_true", help="Show the browser (debug)")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.output:
        config.output_path = args.output
    if args.format:
        config.output_format = args.format

    headed = args.headed or os.environ.get("HEADED", "").lower() == "true"

    results = await aggregator.run(config, headed=headed)
    if not results:
        logger.warning("no results produced — check org errors above")
        return 1

    write(results, config.output_path, config.output_format)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"))
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
