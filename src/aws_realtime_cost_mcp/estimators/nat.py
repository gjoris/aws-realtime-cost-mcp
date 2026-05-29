"""NAT Gateway estimator: fixed hourly + variable per-GB egress.

State (per-NAT $/h) comes from DescribeNatGateways. Variable cost (the silent
killer for data-heavy workloads) comes from CloudWatch BytesOutToDestination
over the last hour, extrapolated to a per-hour rate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .. import cloudwatch
from .base import Resource

SERVICE = "nat_gateway"
PRICING_SERVICE_CODE = "AmazonVPC"

LOCATION_NAMES: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
}

BYTES_PER_GB = Decimal("1073741824")


def _hourly_attrs(region: str) -> dict:
    return {
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "groupDescription": "Hourly charge for NAT Gateways",
        "operation": "NatGateway",
        "usagetype": f"NatGateway-Hours" if region == "us-east-1" else f"{_usage_prefix(region)}-NatGateway-Hours",
    }


def _gb_attrs(region: str) -> dict:
    return {
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "groupDescription": "Per GB Data Processed by NAT Gateways",
        "operation": "NatGateway",
        "usagetype": f"NatGateway-Bytes" if region == "us-east-1" else f"{_usage_prefix(region)}-NatGateway-Bytes",
    }


def _usage_prefix(region: str) -> str:
    """AWS prefixes non-us-east-1 usage types with a region code (EU-, EUC1-, …)."""
    return {
        "eu-west-1": "EU",
        "eu-central-1": "EUC1",
        "us-east-2": "USE2",
        "us-west-2": "USW2",
        "ap-northeast-1": "APN1",
        "ap-southeast-1": "APS1",
    }.get(region, region.upper())


def _hours_between(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds() / 3600))


def list_resources(
    session: Any, region: str, pricing: Any, period_start: datetime
) -> Iterable[Resource]:
    pricing.ensure_loaded(PRICING_SERVICE_CODE, region)

    ec2 = session.client("ec2", region_name=region)
    paginator = ec2.get_paginator("describe_nat_gateways")
    now = datetime.now(timezone.utc)

    hourly_unit = pricing.lookup(PRICING_SERVICE_CODE, region, _hourly_attrs(region))
    if hourly_unit is None:
        hourly_unit = Decimal("0")
    per_gb = pricing.lookup(PRICING_SERVICE_CODE, region, _gb_attrs(region))
    if per_gb is None:
        per_gb = Decimal("0")

    for page in paginator.paginate():
        for gw in page.get("NatGateways", []):
            if gw.get("State") != "available":
                continue

            gw_id = gw["NatGatewayId"]
            bytes_out = cloudwatch.sum_over_last_hour(
                session,
                region,
                namespace="AWS/NATGateway",
                metric_name="BytesOutToDestination",
                dimensions=[{"Name": "NatGatewayId", "Value": gw_id}],
            )
            gb_per_hour = bytes_out / BYTES_PER_GB
            volume_hourly = gb_per_hour * per_gb
            total_hourly = hourly_unit + volume_hourly

            since = gw.get("CreateTime") or now
            if since.tzinfo is None:  # pragma: no cover
                since = since.replace(tzinfo=timezone.utc)
            billable_start = max(since, period_start)
            cumulative = total_hourly * _hours_between(billable_start, now)

            yield Resource(
                service=SERVICE,
                resource_id=gw_id,
                region=region,
                hourly_cost=total_hourly,
                cumulative_cost=cumulative,
                since=since,
                details={
                    "fixed_hourly": str(hourly_unit),
                    "volume_hourly": str(volume_hourly),
                    "gb_per_hour_observed": str(gb_per_hour),
                },
            )
