"""Lazy SQLite cache around the AWS Pricing API.

Pricing data is huge (gigabytes per service) but we only need a few SKUs per
customer per call. So we lazy-load on first access for a given (service,
region) tuple, persist into a small SQLite db, and keep using that until the
TTL expires.

The Pricing API only lives in us-east-1 and ap-south-1. We always query
us-east-1.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

import boto3

PRICING_REGION = "us-east-1"

TTL_BY_SERVICE: dict[str, int] = {
    "AmazonEC2": 30 * 24 * 3600,
    "AmazonRDS": 30 * 24 * 3600,
    "AmazonSageMaker": 30 * 24 * 3600,
    "AmazonVPC": 7 * 24 * 3600,
    "AWSDataTransfer": 7 * 24 * 3600,
    "AmazonBedrock": 30 * 24 * 3600,
}
DEFAULT_TTL = 30 * 24 * 3600


def default_db_path() -> Path:
    override = os.environ.get("AWS_REALTIME_COST_PRICING_DB")
    if override:
        return Path(override)
    return (
        Path.home()
        / ".local"
        / "share"
        / "aws-realtime-cost-mcp"
        / "pricing.db"
    )


class PricingCache:
    """SQLite-backed cache for unit prices keyed by (service, region, attrs)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                service TEXT NOT NULL,
                region TEXT NOT NULL,
                attrs_json TEXT NOT NULL,
                unit_price TEXT NOT NULL,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY (service, region, attrs_json)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prices_service_region "
            "ON prices (service, region)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _is_fresh(self, service: str, fetched_at: int) -> bool:
        ttl = TTL_BY_SERVICE.get(service, DEFAULT_TTL)
        return (time.time() - fetched_at) < ttl

    def _has_fresh_rows(self, service: str, region: str) -> bool:
        cursor = self._conn.execute(
            "SELECT MIN(fetched_at) FROM prices WHERE service = ? AND region = ?",
            (service, region),
        )
        row = cursor.fetchone()
        if not row or row[0] is None:
            return False
        return self._is_fresh(service, int(row[0]))

    def ensure_loaded(
        self,
        service: str,
        region: str,
        loader: Optional[callable] = None,
    ) -> None:
        """Make sure the cache has fresh rows for (service, region).

        If absent or stale, call `loader(service, region)` which must yield
        (attrs_dict, unit_price_decimal) tuples.
        """
        if self._has_fresh_rows(service, region):
            return
        if loader is None:  # pragma: no cover
            loader = _api_loader
        rows = list(loader(service, region))
        now = int(time.time())
        self._conn.execute(
            "DELETE FROM prices WHERE service = ? AND region = ?",
            (service, region),
        )
        self._conn.executemany(
            "INSERT INTO prices (service, region, attrs_json, unit_price, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    service,
                    region,
                    json.dumps(attrs, sort_keys=True),
                    str(price),
                    now,
                )
                for attrs, price in rows
            ],
        )
        self._conn.commit()

    def lookup(
        self, service: str, region: str, attrs: dict
    ) -> Optional[Decimal]:
        """Return the unit price for an exact attrs match, else None."""
        cursor = self._conn.execute(
            "SELECT unit_price FROM prices "
            "WHERE service = ? AND region = ? AND attrs_json = ?",
            (service, region, json.dumps(attrs, sort_keys=True)),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Decimal(row[0])

    def invalidate(self, service: Optional[str] = None) -> int:
        """Drop cached rows for one service (or everything). Returns row count."""
        if service is None:
            cursor = self._conn.execute("DELETE FROM prices")
        else:
            cursor = self._conn.execute(
                "DELETE FROM prices WHERE service = ?", (service,)
            )
        self._conn.commit()
        return cursor.rowcount


def _api_loader(service: str, region: str):  # pragma: no cover
    """Default loader that calls the AWS Pricing API. Heavy, exercised by e2e."""
    client = boto3.client("pricing", region_name=PRICING_REGION)
    paginator = client.get_paginator("get_products")
    pages = paginator.paginate(
        ServiceCode=service,
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
        ],
    )
    for page in pages:
        for raw in page.get("PriceList", []):
            doc = json.loads(raw)
            yield from _flatten_product(doc)


def _flatten_product(doc: dict):  # pragma: no cover
    """Yield (attrs, price) tuples from one Pricing API product document."""
    product = doc.get("product") or {}
    attrs = product.get("attributes") or {}
    on_demand = (doc.get("terms") or {}).get("OnDemand") or {}
    for term in on_demand.values():
        for dim in (term.get("priceDimensions") or {}).values():
            usd = (dim.get("pricePerUnit") or {}).get("USD")
            if usd:
                yield attrs, Decimal(usd)
