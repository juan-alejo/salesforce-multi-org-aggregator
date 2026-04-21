"""Tests for the CSV parser — covers the locale quirks Salesforce ships in the wild:
UTF-8 BOM, semicolon delimiters in Spanish locales, quoted fields with embedded commas."""

from __future__ import annotations

from pathlib import Path

from src.salesforce_client import _parse_csv


def _write(tmp_path: Path, content: str, encoding: str = "utf-8") -> Path:
    f = tmp_path / "report.csv"
    f.write_text(content, encoding=encoding)
    return f


def test_comma_delimited_basic(tmp_path: Path) -> None:
    """Standard English-locale export: comma-separated, UTF-8 no BOM."""
    content = "Name,State,Type\nAcme,NY,Customer\nBeta,CA,Partner\n"

    rows = _parse_csv(_write(tmp_path, content))

    assert len(rows) == 2
    assert rows[0] == {"Name": "Acme", "State": "NY", "Type": "Customer"}
    assert rows[1] == {"Name": "Beta", "State": "CA", "Type": "Partner"}


def test_semicolon_delimited_spanish_locale(tmp_path: Path) -> None:
    """Spanish-locale export: semicolon separator, quoted fields, UTF-8 BOM."""
    content = (
        '\ufeff"Nombre";"Estado";"Tipo"\n'
        '"Acme";"NY";"Cliente"\n'
        '"Burlington Textiles";"NC";"Customer - Direct"\n'
    )

    rows = _parse_csv(_write(tmp_path, content))

    assert len(rows) == 2
    assert rows[0]["Nombre"] == "Acme"
    assert rows[1]["Nombre"] == "Burlington Textiles"


def test_embedded_comma_in_quoted_field(tmp_path: Path) -> None:
    """Account names like 'United Oil & Gas, UK' used to break naive splitters —
    the quoted field must stay intact."""
    content = (
        "Nombre,Pais\n"
        '"United Oil & Gas, UK",UK\n'
        '"United Oil & Gas, Singapore",Singapore\n'
    )

    rows = _parse_csv(_write(tmp_path, content))

    assert rows[0]["Nombre"] == "United Oil & Gas, UK"
    assert rows[1]["Nombre"] == "United Oil & Gas, Singapore"


def test_tab_delimited_fallback(tmp_path: Path) -> None:
    """Sniffer also handles tab-delimited exports."""
    content = "Name\tValue\nAcme\t42\nBeta\t99\n"

    rows = _parse_csv(_write(tmp_path, content))

    assert rows == [{"Name": "Acme", "Value": "42"}, {"Name": "Beta", "Value": "99"}]


def test_empty_file_returns_no_rows(tmp_path: Path) -> None:
    rows = _parse_csv(_write(tmp_path, ""))
    assert rows == []


def test_header_only_no_data_rows(tmp_path: Path) -> None:
    rows = _parse_csv(_write(tmp_path, "Name,State\n"))
    assert rows == []


def test_accented_characters_roundtrip(tmp_path: Path) -> None:
    """UTF-8 BOM + accented chars — stresses the 'utf-8-sig' decode path."""
    content = "\ufeffNombre,Ciudad\nMaría,México\nJosé,São Paulo\n"

    rows = _parse_csv(_write(tmp_path, content))

    assert rows[0] == {"Nombre": "María", "Ciudad": "México"}
    assert rows[1] == {"Nombre": "José", "Ciudad": "São Paulo"}
