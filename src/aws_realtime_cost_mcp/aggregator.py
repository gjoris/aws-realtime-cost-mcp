"""Aggregates per-service estimators into rate/projection summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from . import auth
from .estimators import ALL as ESTIMATORS
from .estimators.base import Resource
from .pricing import PricingCache


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def collect_resources(
    account_id: Optional[str],
    region: str,
    pricing: PricingCache,
    period_start: Optional[datetime] = None,
) -> list[Resource]:
    """Run every registered estimator and return all detected resources."""
    session = auth.get_session(account_id)
    period_start = period_start or _start_of_month(datetime.now(timezone.utc))
    resources: list[Resource] = []
    for est in ESTIMATORS.values():
        resources.extend(est.list_resources(session, region, pricing, period_start))
    return resources


def running_cost_rate(resources: list[Resource]) -> dict:
    """Sum hourly cost per service and total."""
    by_service: dict[str, Decimal] = {}
    total = Decimal("0")
    for r in resources:
        by_service[r.service] = by_service.get(r.service, Decimal("0")) + r.hourly_cost
        total += r.hourly_cost
    return {
        "hourly_total": str(total),
        "hourly_by_service": {k: str(v) for k, v in by_service.items()},
        "resource_count": len(resources),
    }
