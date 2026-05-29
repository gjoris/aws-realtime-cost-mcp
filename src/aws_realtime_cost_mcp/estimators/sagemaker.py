"""SageMaker estimator: ListEndpoints → endpoint instance hourly cost.

Notebook instances and training jobs are out of scope for the MVP — the
runaway pattern we care about is "endpoint forgotten in service after the
demo". An endpoint can have multiple production variants, each with its own
instance type and count.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .base import Resource

SERVICE = "sagemaker"
PRICING_SERVICE_CODE = "AmazonSageMaker"

LOCATION_NAMES: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
}

_BILLABLE_STATUSES = {"InService", "Updating", "RollingBack", "SystemUpdating"}


def _instance_attrs(instance_type: str, region: str) -> dict:
    return {
        "instanceName": instance_type,
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "component": "Hosting",
    }


def _hours_between(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds() / 3600))


def list_resources(
    session: Any, region: str, pricing: Any, period_start: datetime
) -> Iterable[Resource]:
    pricing.ensure_loaded(PRICING_SERVICE_CODE, region)

    client = session.client("sagemaker", region_name=region)
    paginator = client.get_paginator("list_endpoints")
    now = datetime.now(timezone.utc)

    for page in paginator.paginate():
        for endpoint in page.get("Endpoints", []):
            if endpoint.get("EndpointStatus") not in _BILLABLE_STATUSES:
                continue

            name = endpoint["EndpointName"]
            try:
                config_name = client.describe_endpoint(EndpointName=name)[
                    "EndpointConfigName"
                ]
                config = client.describe_endpoint_config(
                    EndpointConfigName=config_name
                )
            except client.exceptions.ClientError:  # pragma: no cover
                continue

            endpoint_hourly = Decimal("0")
            variant_details = []
            for variant in config.get("ProductionVariants", []):
                instance_type = variant.get("InstanceType")
                count = int(variant.get("InitialInstanceCount", 1))
                if instance_type is None:
                    continue
                attrs = _instance_attrs(instance_type, region)
                per_instance = pricing.lookup(PRICING_SERVICE_CODE, region, attrs)
                if per_instance is None:
                    per_instance = Decimal("0")
                endpoint_hourly += per_instance * count
                variant_details.append({
                    "name": variant.get("VariantName"),
                    "instance_type": instance_type,
                    "instance_count": count,
                })

            since = endpoint.get("CreationTime") or now
            if since.tzinfo is None:  # pragma: no cover
                since = since.replace(tzinfo=timezone.utc)
            billable_start = max(since, period_start)
            cumulative = endpoint_hourly * _hours_between(billable_start, now)

            yield Resource(
                service=SERVICE,
                resource_id=name,
                region=region,
                hourly_cost=endpoint_hourly,
                cumulative_cost=cumulative,
                since=since,
                details={"variants": variant_details},
            )
