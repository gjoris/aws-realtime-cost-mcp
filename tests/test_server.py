"""MCP tool wrappers in server.py."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aws_realtime_cost_mcp import server
from aws_realtime_cost_mcp.estimators.base import Resource


@pytest.fixture
def fake_pricing(tmp_path, monkeypatch):
    """Replace _new_pricing with a tmp-path-backed cache so we never write home."""
    from aws_realtime_cost_mcp.pricing import PricingCache

    def _factory():
        return PricingCache(db_path=tmp_path / "pricing.db")

    monkeypatch.setattr(server, "_new_pricing", _factory)
    return _factory


def test_get_running_cost_rate_returns_summary(monkeypatch, fake_pricing):
    def fake_collect(account_id, region, pricing, period_start=None):
        assert account_id is None
        assert region == "eu-west-1"
        return [
            Resource(
                service="ec2",
                resource_id="i-1",
                region="eu-west-1",
                hourly_cost=Decimal("0.10"),
                cumulative_cost=Decimal("1.00"),
                since=datetime.now(timezone.utc),
            )
        ]

    monkeypatch.setattr(server.aggregator, "collect_resources", fake_collect)
    result = server.get_running_cost_rate(region="eu-west-1")
    assert result["hourly_total"] == "0.10"
    assert result["resource_count"] == 1


def test_get_running_cost_rate_with_account_id(monkeypatch, fake_pricing):
    captured = {}

    def fake_collect(account_id, region, pricing, period_start=None):
        captured["account_id"] = account_id
        captured["region"] = region
        return []

    monkeypatch.setattr(server.aggregator, "collect_resources", fake_collect)
    server.get_running_cost_rate(region="us-east-1", account_id="123456789012")
    assert captured == {"account_id": "123456789012", "region": "us-east-1"}


def test_refresh_pricing_clears_specific_service(fake_pricing):
    pricing = server._new_pricing()
    pricing._conn.execute(
        "INSERT INTO prices VALUES (?, ?, ?, ?, ?)",
        ("AmazonEC2", "eu-west-1", "{}", "0.10", 0),
    )
    pricing._conn.commit()
    pricing.close()

    result = server.refresh_pricing(service="AmazonEC2")
    assert result == {"invalidated_rows": 1, "service": "AmazonEC2"}


def test_refresh_pricing_clears_all(fake_pricing):
    pricing = server._new_pricing()
    pricing._conn.execute(
        "INSERT INTO prices VALUES (?, ?, ?, ?, ?)",
        ("AmazonEC2", "eu-west-1", "{}", "0.10", 0),
    )
    pricing._conn.execute(
        "INSERT INTO prices VALUES (?, ?, ?, ?, ?)",
        ("AmazonRDS", "eu-west-1", "{}", "0.20", 0),
    )
    pricing._conn.commit()
    pricing.close()

    result = server.refresh_pricing()
    assert result["invalidated_rows"] == 2
    assert result["service"] is None
