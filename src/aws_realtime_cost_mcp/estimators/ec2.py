"""EC2 estimator: DescribeInstances → on-demand price × hours-since-launch.

Volume-based costs (data transfer, EBS IOPS bursts) are intentionally out of
scope here. They live in their own estimators when added.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .base import Resource

SERVICE = "ec2"
PRICING_SERVICE_CODE = "AmazonEC2"

LOCATION_NAMES: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
}

_RUNNING_STATES = {"pending", "running"}


def _hourly_attrs(instance_type: str, region: str, tenancy: str, os_name: str) -> dict:
    """Build the attrs dict that matches the OnDemand SKU we want."""
    return {
        "instanceType": instance_type,
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "tenancy": tenancy,
        "operatingSystem": os_name,
        "preInstalledSw": "NA",
        "capacitystatus": "Used",
    }


def _platform_to_os(platform_details: str | None) -> str:
    if not platform_details or platform_details == "Linux/UNIX":
        return "Linux"
    if "Windows" in platform_details:
        return "Windows"
    if "Red Hat" in platform_details:
        return "RHEL"
    if "SUSE" in platform_details:
        return "SUSE"
    return "Linux"


def _tenancy_label(value: str | None) -> str:
    if value == "host":
        return "Host"
    if value == "dedicated":
        return "Dedicated"
    return "Shared"


def _hours_between(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(str(delta.total_seconds() / 3600))


def list_resources(
    session: Any, region: str, pricing: Any, period_start: datetime
) -> Iterable[Resource]:
    pricing.ensure_loaded(PRICING_SERVICE_CODE, region)

    client = session.client("ec2", region_name=region)
    paginator = client.get_paginator("describe_instances")
    now = datetime.now(timezone.utc)

    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                state = (instance.get("State") or {}).get("Name")
                if state not in _RUNNING_STATES:
                    continue

                instance_type = instance["InstanceType"]
                tenancy = _tenancy_label(
                    (instance.get("Placement") or {}).get("Tenancy")
                )
                os_name = _platform_to_os(instance.get("PlatformDetails"))
                attrs = _hourly_attrs(instance_type, region, tenancy, os_name)
                hourly = pricing.lookup(PRICING_SERVICE_CODE, region, attrs)
                if hourly is None:
                    hourly = Decimal("0")

                launch_time = instance["LaunchTime"]
                if launch_time.tzinfo is None:  # pragma: no cover
                    launch_time = launch_time.replace(tzinfo=timezone.utc)
                billable_start = max(launch_time, period_start)
                cumulative = hourly * _hours_between(billable_start, now)

                yield Resource(
                    service=SERVICE,
                    resource_id=instance["InstanceId"],
                    region=region,
                    hourly_cost=hourly,
                    cumulative_cost=cumulative,
                    since=launch_time,
                    details={
                        "instance_type": instance_type,
                        "platform": os_name,
                        "tenancy": tenancy,
                    },
                )
