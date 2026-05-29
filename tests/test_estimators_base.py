from datetime import datetime, timezone
from decimal import Decimal

from aws_realtime_cost_mcp.estimators.base import Resource


def test_resource_to_dict_roundtrip():
    when = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
    r = Resource(
        service="ec2",
        resource_id="i-abc",
        region="eu-west-1",
        hourly_cost=Decimal("0.10"),
        cumulative_cost=Decimal("2.40"),
        since=when,
        details={"foo": "bar"},
    )
    d = r.to_dict()
    assert d["service"] == "ec2"
    assert d["resource_id"] == "i-abc"
    assert d["hourly_cost"] == "0.10"
    assert d["cumulative_cost"] == "2.40"
    assert d["since"] == when.isoformat()
    assert d["details"] == {"foo": "bar"}
