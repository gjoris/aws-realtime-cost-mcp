"""Estimator protocol and shared Resource type."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Protocol


@dataclass
class Resource:
    """One billable resource detected via a service API.

    `hourly_cost` is the right-now $/hour run rate. `cumulative_cost` is the
    total since `since` (typically the launch time, or first-of-month if the
    resource was started before the billing period began).
    """

    service: str
    resource_id: str
    region: str
    hourly_cost: Decimal
    cumulative_cost: Decimal
    since: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "resource_id": self.resource_id,
            "region": self.region,
            "hourly_cost": str(self.hourly_cost),
            "cumulative_cost": str(self.cumulative_cost),
            "since": self.since.isoformat(),
            "details": self.details,
        }


class Estimator(Protocol):
    SERVICE: str

    def list_resources(
        self, session: Any, region: str, pricing: Any, period_start: datetime
    ) -> Iterable[Resource]:
        ...  # pragma: no cover
