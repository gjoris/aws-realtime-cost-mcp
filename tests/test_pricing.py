"""PricingCache tests with stubbed loaders so we never call AWS."""

from __future__ import annotations

import os
import time
from decimal import Decimal
from pathlib import Path

import pytest

from aws_realtime_cost_mcp.pricing import (
    DEFAULT_TTL,
    PricingCache,
    default_db_path,
)


def test_default_db_path_uses_home(monkeypatch):
    monkeypatch.delenv("AWS_REALTIME_COST_PRICING_DB", raising=False)
    monkeypatch.setenv("HOME", "/tmp/fakehome")
    expected = Path("/tmp/fakehome/.local/share/aws-realtime-cost-mcp/pricing.db")
    assert default_db_path() == expected


def test_default_db_path_respects_override(monkeypatch, tmp_path):
    override = tmp_path / "elsewhere.db"
    monkeypatch.setenv("AWS_REALTIME_COST_PRICING_DB", str(override))
    assert default_db_path() == override


def test_ensure_loaded_persists_and_lookup(pricing, stub_pricing_loader):
    rows = [
        ({"instanceType": "m5.large", "regionCode": "eu-west-1"}, Decimal("0.107")),
        ({"instanceType": "m5.xlarge", "regionCode": "eu-west-1"}, Decimal("0.214")),
    ]
    pricing.ensure_loaded(
        "AmazonEC2", "eu-west-1", loader=stub_pricing_loader(rows)
    )
    price = pricing.lookup(
        "AmazonEC2",
        "eu-west-1",
        {"instanceType": "m5.large", "regionCode": "eu-west-1"},
    )
    assert price == Decimal("0.107")


def test_ensure_loaded_skips_when_fresh(pricing, stub_pricing_loader):
    calls: list[int] = []

    def counting_loader(rows):
        def _loader(service, region):
            calls.append(1)
            yield from rows

        return _loader

    rows = [({"sku": "a"}, Decimal("1"))]
    pricing.ensure_loaded("AmazonEC2", "eu-west-1", loader=counting_loader(rows))
    pricing.ensure_loaded("AmazonEC2", "eu-west-1", loader=counting_loader(rows))
    assert sum(calls) == 1


def test_ensure_loaded_reloads_when_stale(pricing, stub_pricing_loader, monkeypatch):
    rows_v1 = [({"sku": "a"}, Decimal("1"))]
    rows_v2 = [({"sku": "a"}, Decimal("2"))]

    pricing.ensure_loaded(
        "AmazonEC2", "eu-west-1", loader=stub_pricing_loader(rows_v1)
    )
    # Force expiry: rewrite fetched_at to the deep past.
    expired = int(time.time()) - DEFAULT_TTL - 10
    pricing._conn.execute(
        "UPDATE prices SET fetched_at = ?", (expired,)
    )
    pricing._conn.commit()

    pricing.ensure_loaded(
        "AmazonEC2", "eu-west-1", loader=stub_pricing_loader(rows_v2)
    )
    assert pricing.lookup("AmazonEC2", "eu-west-1", {"sku": "a"}) == Decimal("2")


def test_lookup_returns_none_for_miss(pricing):
    assert pricing.lookup("AmazonEC2", "eu-west-1", {"sku": "absent"}) is None


def test_invalidate_one_service(pricing, stub_pricing_loader):
    pricing.ensure_loaded(
        "AmazonEC2",
        "eu-west-1",
        loader=stub_pricing_loader([({"sku": "a"}, Decimal("1"))]),
    )
    pricing.ensure_loaded(
        "AmazonRDS",
        "eu-west-1",
        loader=stub_pricing_loader([({"sku": "b"}, Decimal("2"))]),
    )
    rows = pricing.invalidate("AmazonEC2")
    assert rows == 1
    assert pricing.lookup("AmazonEC2", "eu-west-1", {"sku": "a"}) is None
    assert pricing.lookup("AmazonRDS", "eu-west-1", {"sku": "b"}) == Decimal("2")


def test_invalidate_all(pricing, stub_pricing_loader):
    pricing.ensure_loaded(
        "AmazonEC2",
        "eu-west-1",
        loader=stub_pricing_loader([({"sku": "a"}, Decimal("1"))]),
    )
    rows = pricing.invalidate()
    assert rows == 1
    assert pricing.lookup("AmazonEC2", "eu-west-1", {"sku": "a"}) is None


def test_init_creates_parent_dir(tmp_path):
    nested = tmp_path / "deep" / "nested" / "pricing.db"
    cache = PricingCache(db_path=nested)
    cache.close()
    assert nested.parent.is_dir()
