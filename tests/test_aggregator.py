"""Aggregator tests with stubbed estimators."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from aws_realtime_cost_mcp import aggregator
from aws_realtime_cost_mcp.estimators.base import Resource


class _FakeEstimator:
    SERVICE = "ec2"

    def __init__(self, resources):
        self._resources = resources

    def list_resources(self, session, region, pricing, period_start):
        return self._resources


def _resource(service: str, hourly: str) -> Resource:
    return Resource(
        service=service,
        resource_id="r1",
        region="eu-west-1",
        hourly_cost=Decimal(hourly),
        cumulative_cost=Decimal("0"),
        since=datetime.now(timezone.utc),
    )


def test_running_cost_rate_sums_per_service():
    resources = [
        _resource("ec2", "0.10"),
        _resource("ec2", "0.20"),
        _resource("rds", "0.50"),
    ]
    summary = aggregator.running_cost_rate(resources)
    assert summary["hourly_total"] == "0.80"
    assert summary["hourly_by_service"] == {"ec2": "0.30", "rds": "0.50"}
    assert summary["resource_count"] == 3


def test_running_cost_rate_empty():
    summary = aggregator.running_cost_rate([])
    assert summary["hourly_total"] == "0"
    assert summary["hourly_by_service"] == {}
    assert summary["resource_count"] == 0


def test_collect_resources_calls_each_estimator(monkeypatch, pricing):
    fake = _FakeEstimator([_resource("ec2", "0.10")])
    monkeypatch.setattr(aggregator, "ESTIMATORS", {"ec2": fake})
    resources = aggregator.collect_resources(None, "eu-west-1", pricing)
    assert len(resources) == 1
    assert resources[0].service == "ec2"


def test_collect_resources_uses_period_start_default(monkeypatch, pricing):
    captured: list[datetime] = []

    class _Capturing:
        SERVICE = "ec2"

        def list_resources(self, session, region, pricing, period_start):
            captured.append(period_start)
            return []

    monkeypatch.setattr(aggregator, "ESTIMATORS", {"ec2": _Capturing()})
    aggregator.collect_resources(None, "eu-west-1", pricing)
    assert captured
    ps = captured[0]
    assert ps.day == 1
    assert ps.hour == 0


def test_collect_resources_respects_explicit_period_start(monkeypatch, pricing):
    captured: list[datetime] = []

    class _Capturing:
        SERVICE = "ec2"

        def list_resources(self, session, region, pricing, period_start):
            captured.append(period_start)
            return []

    monkeypatch.setattr(aggregator, "ESTIMATORS", {"ec2": _Capturing()})
    pinned = datetime(2026, 1, 15, tzinfo=timezone.utc)
    aggregator.collect_resources(None, "eu-west-1", pricing, period_start=pinned)
    assert captured == [pinned]
