"""MCP server exposing real-time AWS cost estimation tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from . import aggregator, coverage as coverage_mod
from .pricing import PricingCache

mcp = FastMCP("aws-realtime-cost")


def _new_pricing() -> PricingCache:  # pragma: no cover
    return PricingCache()


@mcp.tool()
def get_running_cost_rate(
    region: str,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """Return the current $/hour run rate for all detected resources.

    Args:
        region: AWS region code (e.g. "eu-west-1").
        account_id: Optional AWS account ID. If set, the server assumes a
            cross-account reader role; otherwise it uses local credentials.

    Returns:
        Dict with hourly_total, hourly_by_service, and resource_count.
    """
    pricing = _new_pricing()
    try:
        resources = aggregator.collect_resources(account_id, region, pricing)
        return aggregator.running_cost_rate(resources)
    finally:
        pricing.close()


@mcp.tool()
def project_month_end_spend(
    region: str,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """Project the total spend for the rest of the calendar month.

    Returns cumulative_so_far, hourly_rate, remaining_hours_in_month,
    projected_month_end. Naively assumes the current rate stays constant; for
    workloads with strong daily/weekly patterns this is a lower bound on
    accuracy, not a guarantee.
    """
    pricing = _new_pricing()
    try:
        resources = aggregator.collect_resources(account_id, region, pricing)
        return aggregator.project_month_end_spend(resources)
    finally:
        pricing.close()


@mcp.tool()
def list_expensive_resources(
    region: str,
    threshold_per_hour: float = 1.0,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """List resources whose hourly cost exceeds threshold, sorted descending.

    Args:
        region: AWS region code.
        threshold_per_hour: Min $/hour to include (default 1.0).
        account_id: Optional cross-account target.

    Returns:
        Dict with `threshold_per_hour` and `resources` (list of resource dicts).
    """
    pricing = _new_pricing()
    try:
        resources = aggregator.collect_resources(account_id, region, pricing)
        return {
            "threshold_per_hour": str(threshold_per_hour),
            "resources": aggregator.expensive_resources(
                resources, Decimal(str(threshold_per_hour))
            ),
        }
    finally:
        pricing.close()


@mcp.tool()
def get_coverage_report(
    region: str,
    account_id: Optional[str] = None,
) -> dict[str, Any]:
    """Report which services are covered by an estimator and which uncovered services have running resources.

    Use this before trusting `get_running_cost_rate` for a complete picture: a
    high-cost service that doesn't have an estimator (OpenSearch, Redshift,
    MSK) will not show up in the rate, but will appear here as
    `unmeasured_running_services`.
    """
    return coverage_mod.report(account_id, region)


@mcp.tool()
def compare_estimate_vs_actual(days_ago: int = 2) -> dict[str, Any]:
    """Compare a snapshotted estimate against AWS Cost Explorer actuals.

    Requires history-mode (snapshots persisted across calls), which lands in a
    later release. The current build returns a placeholder so callers can see
    the eventual tool shape.
    """
    return {
        "error": "compare_estimate_vs_actual requires history mode (not enabled in this build)",
        "days_ago": days_ago,
        "needs_history": True,
    }


@mcp.tool()
def refresh_pricing(service: Optional[str] = None) -> dict[str, Any]:
    """Drop cached pricing rows so the next call reloads from the AWS Pricing API.

    Args:
        service: Pricing API service code (e.g. "AmazonEC2"). If omitted, the
            entire cache is cleared.
    """
    pricing = _new_pricing()
    try:
        rows = pricing.invalidate(service)
        return {"invalidated_rows": rows, "service": service}
    finally:
        pricing.close()


def main() -> None:  # pragma: no cover
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
