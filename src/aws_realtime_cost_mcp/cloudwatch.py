"""Tiny wrapper around CloudWatch GetMetricData.

We always ask for a 60-minute window ending now and request a single
aggregated value back. That keeps the GetMetricData cost under $0.0001 per
estimator call (3 metrics × $0.01 / 1000) which is well below the cost we are
trying to detect.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


def sum_over_last_hour(
    session: Any,
    region: str,
    namespace: str,
    metric_name: str,
    dimensions: list[dict],
    stat: str = "Sum",
) -> Decimal:
    """Return the sum (or chosen stat) of one CloudWatch metric over the last 60 min.

    Returns Decimal('0') if the metric has no datapoints — which is the same
    semantics as "the resource hasn't done anything billable in the window".
    """
    client = session.client("cloudwatch", region_name=region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=60)
    response = client.get_metric_data(
        MetricDataQueries=[
            {
                "Id": "m1",
                "MetricStat": {
                    "Metric": {
                        "Namespace": namespace,
                        "MetricName": metric_name,
                        "Dimensions": dimensions,
                    },
                    "Period": 3600,
                    "Stat": stat,
                },
                "ReturnData": True,
            }
        ],
        StartTime=start,
        EndTime=end,
        ScanBy="TimestampDescending",
    )
    results = response.get("MetricDataResults", [])
    if not results:
        return Decimal("0")
    values = results[0].get("Values", [])
    if not values:
        return Decimal("0")
    return Decimal(str(values[0]))
