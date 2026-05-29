"""NAT Gateway estimator tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp.estimators import nat as nat_estimator
from aws_realtime_cost_mcp.estimators.nat import (
    BYTES_PER_GB,
    LOCATION_NAMES,
    PRICING_SERVICE_CODE,
    _gb_attrs,
    _hourly_attrs,
    _usage_prefix,
    list_resources,
)


@pytest.fixture
def loaded_pricing(pricing, stub_pricing_loader):
    rows = [
        (_hourly_attrs("eu-west-1"), Decimal("0.052")),
        (_gb_attrs("eu-west-1"), Decimal("0.052")),
    ]
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE, "eu-west-1", loader=stub_pricing_loader(rows)
    )
    return pricing


def _create_nat(region: str = "eu-west-1") -> str:
    ec2 = boto3.client("ec2", region_name=region)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    eip = ec2.allocate_address(Domain="vpc")["AllocationId"]
    nat = ec2.create_nat_gateway(SubnetId=subnet, AllocationId=eip)["NatGateway"]
    return nat["NatGatewayId"]


@mock_aws
def test_available_nat_yields_resource(loaded_pricing, monkeypatch):
    nat_id = _create_nat()

    monkeypatch.setattr(
        nat_estimator.cloudwatch,
        "sum_over_last_hour",
        lambda *a, **kw: BYTES_PER_GB * Decimal("10"),
    )

    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert len(resources) == 1
    r = resources[0]
    assert r.resource_id == nat_id
    assert r.hourly_cost == Decimal("0.052") + (Decimal("10") * Decimal("0.052"))
    assert r.details["fixed_hourly"] == "0.052"


@mock_aws
def test_pending_nat_skipped(loaded_pricing, monkeypatch):
    _create_nat()

    monkeypatch.setattr(
        nat_estimator.cloudwatch, "sum_over_last_hour", lambda *a, **kw: Decimal("0")
    )

    session = boto3.Session(region_name="eu-west-1")
    real_client = session.client

    real_describe = real_client("ec2").describe_nat_gateways

    def force_pending(*args, **kwargs):
        result = real_describe(*args, **kwargs)
        for gw in result["NatGateways"]:
            gw["State"] = "pending"
        return result

    def patched_client(name, **kw):
        c = real_client(name, **kw)
        if name == "ec2":
            monkeypatch.setattr(c, "describe_nat_gateways", force_pending)
        return c

    monkeypatch.setattr(session, "client", patched_client)

    resources = list(
        list_resources(
            session,
            "eu-west-1",
            loaded_pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert resources == []


@mock_aws
def test_unknown_pricing_uses_zero(pricing, stub_pricing_loader, monkeypatch):
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE,
        "eu-west-1",
        loader=stub_pricing_loader([({"unrelated": "x"}, Decimal("1"))]),
    )
    _create_nat()
    monkeypatch.setattr(
        nat_estimator.cloudwatch,
        "sum_over_last_hour",
        lambda *a, **kw: Decimal("0"),
    )

    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert len(resources) == 1
    assert resources[0].hourly_cost == Decimal("0")


def test_usage_prefix_known_and_unknown():
    assert _usage_prefix("eu-west-1") == "EU"
    assert _usage_prefix("eu-central-1") == "EUC1"
    assert _usage_prefix("xx-zone-9") == "XX-ZONE-9"


def test_hourly_attrs_us_east_1_no_prefix():
    attrs = _hourly_attrs("us-east-1")
    assert attrs["usagetype"] == "NatGateway-Hours"


def test_hourly_attrs_other_region_has_prefix():
    attrs = _hourly_attrs("eu-west-1")
    assert attrs["usagetype"] == "EU-NatGateway-Hours"


def test_gb_attrs_us_east_1_no_prefix():
    assert _gb_attrs("us-east-1")["usagetype"] == "NatGateway-Bytes"


def test_gb_attrs_other_region_has_prefix():
    assert _gb_attrs("eu-central-1")["usagetype"] == "EUC1-NatGateway-Bytes"


def test_location_unknown_falls_through():
    assert _hourly_attrs("us-gov-west-1")["location"] == "us-gov-west-1"


def test_location_known():
    assert _hourly_attrs("eu-west-1")["location"] == LOCATION_NAMES["eu-west-1"]
