"""Aggregates per-service estimators into rate/projection summaries."""

from __future__ import annotations

import calendar
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


def project_month_end_spend(
    resources: list[Resource], now: Optional[datetime] = None
) -> dict:
    """Combine cumulative-so-far + extrapolation of current rate to month end."""
    now = now or datetime.now(timezone.utc)
    cumulative = sum((r.cumulative_cost for r in resources), Decimal("0"))
    hourly = sum((r.hourly_cost for r in resources), Decimal("0"))

    days_in_month = calendar.monthrange(now.year, now.month)[1]
    end_of_month = now.replace(
        day=days_in_month, hour=23, minute=59, second=59, microsecond=0
    )
    remaining_hours = Decimal(
        str((end_of_month - now).total_seconds() / 3600)
    )
    if remaining_hours < 0:
        remaining_hours = Decimal("0")

    projected = cumulative + (hourly * remaining_hours)
    return {
        "cumulative_so_far": str(cumulative),
        "hourly_rate": str(hourly),
        "remaining_hours_in_month": str(remaining_hours),
        "projected_month_end": str(projected),
    }


def expensive_resources(
    resources: list[Resource], threshold_per_hour: Decimal
) -> list[dict]:
    """Resources whose hourly cost exceeds the threshold, sorted descending."""
    filtered = [r for r in resources if r.hourly_cost >= threshold_per_hour]
    filtered.sort(key=lambda r: r.hourly_cost, reverse=True)
    return [r.to_dict() for r in filtered]
