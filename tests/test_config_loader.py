from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import AppConfig, load_config

VALID_YAML = """
concurrency: 2
output_format: csv
output_path: out/report
orgs:
  - name: Org-A
    login_url: https://login.salesforce.com
    username_env: A_USER
    password_env: A_PASS
    reports:
      - id: "001"
        name: R1
  - name: Org-B
    login_url: https://test.salesforce.com
    username_env: B_USER
    password_env: B_PASS
    reports:
      - id: "002"
        name: R2
"""


def test_load_valid_config(tmp_path: Path) -> None:
    f = tmp_path / "orgs.yaml"
    f.write_text(VALID_YAML)

    cfg = load_config(f)

    assert isinstance(cfg, AppConfig)
    assert cfg.concurrency == 2
    assert cfg.output_format == "csv"
    assert [o.name for o in cfg.orgs] == ["Org-A", "Org-B"]


def test_duplicate_org_names_rejected(tmp_path: Path) -> None:
    dup = VALID_YAML.replace("Org-B", "Org-A")
    f = tmp_path / "orgs.yaml"
    f.write_text(dup)

    with pytest.raises(ValueError, match="unique"):
        load_config(f)


def test_env_credentials_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A_USER", "alice@example.com")
    monkeypatch.setenv("A_PASS", "s3cret")
    monkeypatch.setenv("B_USER", "bob@example.com")
    monkeypatch.setenv("B_PASS", "s3cret")

    f = tmp_path / "orgs.yaml"
    f.write_text(VALID_YAML)

    cfg = load_config(f)

    assert cfg.orgs[0].username == "alice@example.com"
    assert cfg.orgs[0].password == "s3cret"


def test_missing_env_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A_USER", raising=False)

    f = tmp_path / "orgs.yaml"
    f.write_text(VALID_YAML)

    cfg = load_config(f)

    with pytest.raises(RuntimeError, match="A_USER"):
        _ = cfg.orgs[0].username
