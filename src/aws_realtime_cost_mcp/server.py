"""MCP server exposing real-time AWS cost estimation tools."""

from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from . import aggregator
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
