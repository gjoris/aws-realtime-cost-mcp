"""Bedrock estimator: pure CloudWatch volume, no instance state.

Bedrock has no "endpoint" concept the way SageMaker does — you pay per token.
We pull `InputTokenCount` and `OutputTokenCount` from `AWS/Bedrock` over the
last hour for every model that emitted any traffic and price them per 1k
tokens.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from .. import cloudwatch
from .base import Resource

SERVICE = "bedrock"
PRICING_SERVICE_CODE = "AmazonBedrock"

LOCATION_NAMES: dict[str, str] = {
    "us-east-1": "US East (N. Virginia)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
}

PER_1K = Decimal("1000")


def _input_attrs(region: str, model_id: str) -> dict:
    return {
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "model": model_id,
        "feature": "OnDemand-Input",
    }


def _output_attrs(region: str, model_id: str) -> dict:
    return {
        "location": LOCATION_NAMES.get(region, region),
        "regionCode": region,
        "model": model_id,
        "feature": "OnDemand-Output",
    }


def _list_active_models(session: Any, region: str) -> list[str]:
    """Find Bedrock model IDs that emitted CloudWatch metrics in the last hour."""
    client = session.client("cloudwatch", region_name=region)
    paginator = client.get_paginator("list_metrics")
    pages = paginator.paginate(
        Namespace="AWS/Bedrock", MetricName="InputTokenCount"
    )
    seen: set[str] = set()
    for page in pages:
        for metric in page.get("Metrics", []):
            for dim in metric.get("Dimensions", []):
                if dim["Name"] == "ModelId":
                    seen.add(dim["Value"])
    return sorted(seen)


def list_resources(
    session: Any, region: str, pricing: Any, period_start: datetime
) -> Iterable[Resource]:
    pricing.ensure_loaded(PRICING_SERVICE_CODE, region)
    now = datetime.now(timezone.utc)

    for model_id in _list_active_models(session, region):
        input_tokens = cloudwatch.sum_over_last_hour(
            session,
            region,
            namespace="AWS/Bedrock",
            metric_name="InputTokenCount",
            dimensions=[{"Name": "ModelId", "Value": model_id}],
        )
        output_tokens = cloudwatch.sum_over_last_hour(
            session,
            region,
            namespace="AWS/Bedrock",
            metric_name="OutputTokenCount",
            dimensions=[{"Name": "ModelId", "Value": model_id}],
        )

        input_unit = pricing.lookup(
            PRICING_SERVICE_CODE, region, _input_attrs(region, model_id)
        ) or Decimal("0")
        output_unit = pricing.lookup(
            PRICING_SERVICE_CODE, region, _output_attrs(region, model_id)
        ) or Decimal("0")

        hourly = (input_tokens / PER_1K) * input_unit + (
            output_tokens / PER_1K
        ) * output_unit

        if hourly == Decimal("0") and input_tokens == Decimal("0") and output_tokens == Decimal("0"):
            continue

        yield Resource(
            service=SERVICE,
            resource_id=model_id,
            region=region,
            hourly_cost=hourly,
            cumulative_cost=Decimal("0"),
            since=now,
            details={
                "input_tokens_last_hour": str(input_tokens),
                "output_tokens_last_hour": str(output_tokens),
            },
        )
