"""Shared test fixtures: in-memory pricing cache + moto AWS mocks."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from aws_realtime_cost_mcp import auth as auth_mod
from aws_realtime_cost_mcp.pricing import PricingCache


@pytest.fixture(autouse=True)
def _aws_test_env(monkeypatch):
    """Force fake AWS creds so boto3 never picks up the developer's profile."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    auth_mod.clear_cache()
    yield
    auth_mod.clear_cache()


@pytest.fixture
def pricing(tmp_path: Path) -> PricingCache:
    cache = PricingCache(db_path=tmp_path / "pricing.db")
    yield cache
    cache.close()


@pytest.fixture
def stub_pricing_loader():
    """Build a loader that yields fixed (attrs, price) tuples."""

    def _build(rows: list[tuple[dict, Decimal]]):
        def loader(service: str, region: str):
            yield from rows

        return loader

    return _build
