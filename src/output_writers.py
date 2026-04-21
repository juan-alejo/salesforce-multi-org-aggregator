"""Output writers — CSV, SQLite, XLSX.

Each writer takes the merged list of ReportResult and a base path (no extension);
the writer appends the right extension and creates the parent directory.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from loguru import logger

from .salesforce_client import ReportResult


def write(results: list[ReportResult], base_path: str, output_format: str) -> Path:
    df = _flatten(results)
    base = Path(base_path)
    base.parent.mkdir(parents=True, exist_ok=True)

    match output_format:
        case "csv":
            out = base.with_suffix(".csv")
            df.to_csv(out, index=False)
        case "xlsx":
            out = base.with_suffix(".xlsx")
            df.to_excel(out, index=False, engine="openpyxl")
        case "sqlite":
            out = base.with_suffix(".sqlite")
            with sqlite3.connect(out) as conn:
                df.to_sql("reports", conn, if_exists="replace", index=False)
        case _:
            raise ValueError(f"unknown output_format: {output_format}")

    logger.info(f"wrote {len(df)} row(s) to {out}")
    return out


def _flatten(results: list[ReportResult]) -> pd.DataFrame:
    records = []
    for r in results:
        for row in r.rows:
            records.append({"_org": r.org, "_report": r.report_name, **row})
    return pd.DataFrame(records)
