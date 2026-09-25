"""Shared fixtures. (Client/aggregation fixtures land with steps 2-3.)"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def make_config(tmp_path: Path):
    """Write a YAML config file and return the path."""

    def _make(data: dict, name: str = "weather.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    return _make
