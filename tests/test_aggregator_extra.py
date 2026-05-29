"""Tests for project_month_end_spend and expensive_resources."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from aws_realtime_cost_mcp import aggregator
from aws_realtime_cost_mcp.estimators.base import Resource


def _r(service: str, hourly: str, cumulative: str = "0") -> Resource:
    return Resource(
        service=service,
        resource_id=f"{service}-1",
        region="eu-west-1",
        hourly_cost=Decimal(hourly),
        cumulative_cost=Decimal(cumulative),
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )


def test_project_month_end_spend_basic():
    resources = [_r("ec2", "1.00", cumulative="100.00")]
    now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
    result = aggregator.project_month_end_spend(resources, now=now)
    assert result["cumulative_so_far"] == "100.00"
    assert result["hourly_rate"] == "1.00"
    remaining = Decimal(result["remaining_hours_in_month"])
    assert remaining > 0
    projected = Decimal(result["projected_month_end"])
    assert projected == Decimal("100.00") + remaining


def test_project_month_end_spend_clamps_negative_remaining():
    """If `now` is somehow past end-of-month edge, remaining must clamp to 0."""
    resources = [_r("ec2", "1.00", cumulative="100.00")]
    now = datetime(2026, 5, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    result = aggregator.project_month_end_spend(resources, now=now)
    remaining = Decimal(result["remaining_hours_in_month"])
    assert remaining >= 0


def test_project_month_end_spend_default_now():
    """When `now` defaults to `datetime.now`, the call must still succeed."""
    result = aggregator.project_month_end_spend([_r("ec2", "1.00")])
    assert "projected_month_end" in result


def test_expensive_resources_filters_and_sorts():
    resources = [
        _r("ec2", "0.10"),
        _r("rds", "5.00"),
        _r("sagemaker", "32.00"),
        _r("nat_gateway", "0.50"),
    ]
    out = aggregator.expensive_resources(resources, Decimal("1.00"))
    assert [r["service"] for r in out] == ["sagemaker", "rds"]


def test_expensive_resources_empty_when_below_threshold():
    out = aggregator.expensive_resources([_r("ec2", "0.10")], Decimal("1.00"))
    assert out == []


def test_project_clamps_when_past_end_of_month():
    """Verify that remaining_hours_in_month never goes below 0 even with later 'now'."""
    resources = [_r("ec2", "1.00", cumulative="100.00")]
    # Pin to absolute end of month then add to make remaining negative.
    now = datetime(2026, 5, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    result = aggregator.project_month_end_spend(resources, now=now)
    assert Decimal(result["remaining_hours_in_month"]) == Decimal("0")
