"""RDS estimator: DescribeDBInstances → instance + storage hourly cost.

Aurora is treated like RDS for instance hours; storage is harder (per-GB-month
on consumed bytes, not allocated) and is left for a later iteration. We only
emit the instance-hour line item here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .base import Resource

SERVICE = "rds"
PRICING_SERVICE_CODE = "AmazonRDS"

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

ENGINE_DATABASE_NAMES: dict[str, str] = {
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "mariadb": "MariaDB",
    "oracle-ee": "Oracle",
    "oracle-se2": "Oracle",
    "sqlserver-ee": "SQL Server",
    "sqlserver-se": "SQL Server",
    "sqlserver-ex": "SQL Server",
    "sqlserver-web": "SQL Server",
    "aurora-mysql": "Aurora MySQL",
    "aurora-postgresql": "Aurora PostgreSQL",
}

_BILLABLE_STATES = {
    "available",
    "backing-up",
    "modifying",
    "rebooting",
    "starting",
    "storage-optimization",
    "configuring-enhanced-monitoring",
}


def _instance_attrs(
    instance_class: str, region: str, engine: str, multi_az: bool
) -> dict:
    return {
        "instanceType": instance_class,
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "databaseEngine": ENGINE_DATABASE_NAMES.get(engine, engine),
        "deploymentOption": "Multi-AZ" if multi_az else "Single-AZ",
    }


def _hours_between(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds() / 3600))


def list_resources(
    session: Any, region: str, pricing: Any, period_start: datetime
) -> Iterable[Resource]:
    pricing.ensure_loaded(PRICING_SERVICE_CODE, region)

    client = session.client("rds", region_name=region)
    paginator = client.get_paginator("describe_db_instances")
    now = datetime.now(timezone.utc)

    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            if db.get("DBInstanceStatus") not in _BILLABLE_STATES:
                continue

            attrs = _instance_attrs(
                db["DBInstanceClass"],
                region,
                db.get("Engine", ""),
                bool(db.get("MultiAZ")),
            )
            hourly = pricing.lookup(PRICING_SERVICE_CODE, region, attrs)
            if hourly is None:
                hourly = Decimal("0")

            since = db.get("InstanceCreateTime") or now
            if since.tzinfo is None:  # pragma: no cover
                since = since.replace(tzinfo=timezone.utc)
            billable_start = max(since, period_start)
            cumulative = hourly * _hours_between(billable_start, now)

            yield Resource(
                service=SERVICE,
                resource_id=db["DBInstanceIdentifier"],
                region=region,
                hourly_cost=hourly,
                cumulative_cost=cumulative,
                since=since,
                details={
                    "instance_class": db["DBInstanceClass"],
                    "engine": db.get("Engine"),
                    "multi_az": bool(db.get("MultiAZ")),
                },
            )
