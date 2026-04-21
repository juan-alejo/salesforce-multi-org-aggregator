"""Config loading and validation.

The YAML is parsed into strongly-typed Pydantic models so invalid config
fails at startup with a clear error, not mid-run inside the browser driver.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class ReportConfig(BaseModel):
    id: str
    name: str


class OrgConfig(BaseModel):
    name: str
    login_url: str
    username_env: str
    password_env: str
    reports: list[ReportConfig] = Field(min_length=1)

    @property
    def username(self) -> str:
        return _require_env(self.username_env)

    @property
    def password(self) -> str:
        return _require_env(self.password_env)


class AppConfig(BaseModel):
    concurrency: int = Field(default=4, ge=1, le=32)
    output_format: Literal["csv", "sqlite", "xlsx"] = "csv"
    output_path: str = "out/report"
    orgs: list[OrgConfig] = Field(min_length=1)

    @field_validator("orgs")
    @classmethod
    def _unique_org_names(cls, orgs: list[OrgConfig]) -> list[OrgConfig]:
        names = [o.name for o in orgs]
        if len(names) != len(set(names)):
            raise ValueError("org names must be unique")
        return orgs


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"required environment variable {key!r} is not set")
    return value
