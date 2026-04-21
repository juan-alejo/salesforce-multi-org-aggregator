"""Tests for output writers — each format should preserve rows faithfully
and tag each row with its source org / report."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.output_writers import write
from src.salesforce_client import ReportResult


@pytest.fixture
def sample_results() -> list[ReportResult]:
    return [
        ReportResult(
            org="Org-A",
            report_name="Weekly",
            rows=[
                {"Account": "Acme", "State": "NY"},
                {"Account": "Beta", "State": "CA"},
            ],
        ),
        ReportResult(
            org="Org-B",
            report_name="Weekly",
            rows=[{"Account": "Gamma", "State": "TX"}],
        ),
    ]


def test_csv_output_includes_org_and_report_columns(
    tmp_path: Path, sample_results: list[ReportResult]
) -> None:
    out = write(sample_results, str(tmp_path / "out"), "csv")

    assert out.exists()
    assert out.suffix == ".csv"

    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 3
    assert rows[0]["_org"] == "Org-A"
    assert rows[0]["_report"] == "Weekly"
    assert rows[0]["Account"] == "Acme"
    assert {r["_org"] for r in rows} == {"Org-A", "Org-B"}


def test_xlsx_output_roundtrip(
    tmp_path: Path, sample_results: list[ReportResult]
) -> None:
    out = write(sample_results, str(tmp_path / "out"), "xlsx")

    assert out.suffix == ".xlsx"
    df = pd.read_excel(out)
    assert len(df) == 3
    assert list(df.columns) == ["_org", "_report", "Account", "State"]


def test_sqlite_output_is_queryable(
    tmp_path: Path, sample_results: list[ReportResult]
) -> None:
    out = write(sample_results, str(tmp_path / "out"), "sqlite")

    assert out.suffix == ".sqlite"
    with sqlite3.connect(out) as conn:
        rows = conn.execute(
            "SELECT _org, Account FROM reports ORDER BY _org, Account"
        ).fetchall()

    assert rows == [("Org-A", "Acme"), ("Org-A", "Beta"), ("Org-B", "Gamma")]


def test_empty_results_writes_empty_file(tmp_path: Path) -> None:
    out = write([], str(tmp_path / "out"), "csv")

    assert out.exists()
    with out.open(encoding="utf-8") as f:
        assert f.read().strip() == ""


def test_unknown_format_raises(
    tmp_path: Path, sample_results: list[ReportResult]
) -> None:
    with pytest.raises(ValueError, match="unknown output_format"):
        write(sample_results, str(tmp_path / "out"), "json")


def test_output_directory_is_created(
    tmp_path: Path, sample_results: list[ReportResult]
) -> None:
    """Writer should mkdir parents rather than failing on missing directory."""
    nested = tmp_path / "a" / "b" / "c" / "out"

    out = write(sample_results, str(nested), "csv")

    assert out.exists()
    assert out.parent == tmp_path / "a" / "b" / "c"
