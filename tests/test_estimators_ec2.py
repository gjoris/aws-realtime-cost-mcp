"""EC2 estimator tests against moto-mocked DescribeInstances."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp.estimators import ec2 as ec2_estimator
from aws_realtime_cost_mcp.estimators.ec2 import (
    PRICING_SERVICE_CODE,
    LOCATION_NAMES,
    _hourly_attrs,
    _platform_to_os,
    _tenancy_label,
    list_resources,
)


@pytest.fixture
def loaded_pricing(pricing, stub_pricing_loader):
    rows = [
        (
            _hourly_attrs("t3.micro", "eu-west-1", "Shared", "Linux"),
            Decimal("0.0114"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Shared", "Linux"),
            Decimal("0.107"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Shared", "Windows"),
            Decimal("0.214"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Dedicated", "Linux"),
            Decimal("0.118"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Host", "Linux"),
            Decimal("0.000"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Shared", "RHEL"),
            Decimal("0.167"),
        ),
        (
            _hourly_attrs("m5.large", "eu-west-1", "Shared", "SUSE"),
            Decimal("0.157"),
        ),
    ]
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE, "eu-west-1", loader=stub_pricing_loader(rows)
    )
    return pricing


@mock_aws
def test_running_instance_yields_resource(loaded_pricing):
    ec2 = boto3.client("ec2", region_name="eu-west-1")
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    response = ec2.run_instances(
        ImageId=image_id, InstanceType="m5.large", MinCount=1, MaxCount=1
    )
    instance_id = response["Instances"][0]["InstanceId"]

    period_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            period_start,
        )
    )
    assert len(resources) == 1
    r = resources[0]
    assert r.service == "ec2"
    assert r.resource_id == instance_id
    assert r.hourly_cost == Decimal("0.107")
    assert r.cumulative_cost > Decimal("0")
    assert r.details["instance_type"] == "m5.large"
    assert r.details["platform"] == "Linux"


@mock_aws
def test_stopped_instance_skipped(loaded_pricing):
    ec2 = boto3.client("ec2", region_name="eu-west-1")
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    response = ec2.run_instances(
        ImageId=image_id, InstanceType="m5.large", MinCount=1, MaxCount=1
    )
    iid = response["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[iid])

    period_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            period_start,
        )
    )
    assert resources == []


@mock_aws
def test_unknown_pricing_falls_back_to_zero(loaded_pricing):
    ec2 = boto3.client("ec2", region_name="eu-west-1")
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    ec2.run_instances(
        ImageId=image_id, InstanceType="t3.nano", MinCount=1, MaxCount=1
    )
    period_start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            period_start,
        )
    )
    assert len(resources) == 1
    assert resources[0].hourly_cost == Decimal("0")


@mock_aws
def test_cumulative_cost_uses_period_start_when_launch_earlier(loaded_pricing):
    ec2 = boto3.client("ec2", region_name="eu-west-1")
    image_id = ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]
    ec2.run_instances(
        ImageId=image_id, InstanceType="m5.large", MinCount=1, MaxCount=1
    )

    far_future_period_start = datetime(2099, 1, 1, tzinfo=timezone.utc)
    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            far_future_period_start,
        )
    )
    assert len(resources) == 1
    assert resources[0].cumulative_cost <= Decimal("0")


def test_platform_to_os_branches():
    assert _platform_to_os(None) == "Linux"
    assert _platform_to_os("Linux/UNIX") == "Linux"
    assert _platform_to_os("Windows with SQL") == "Windows"
    assert _platform_to_os("Red Hat Enterprise Linux") == "RHEL"
    assert _platform_to_os("SUSE Linux Enterprise") == "SUSE"
    assert _platform_to_os("Some unknown platform") == "Linux"


def test_tenancy_label_branches():
    assert _tenancy_label("default") == "Shared"
    assert _tenancy_label(None) == "Shared"
    assert _tenancy_label("dedicated") == "Dedicated"
    assert _tenancy_label("host") == "Host"


def test_location_names_fallback_for_unknown_region():
    attrs = _hourly_attrs("m5.large", "us-gov-west-1", "Shared", "Linux")
    assert attrs["location"] == "us-gov-west-1"


def test_location_names_for_known_region():
    attrs = _hourly_attrs("m5.large", "us-east-1", "Shared", "Linux")
    assert attrs["location"] == LOCATION_NAMES["us-east-1"]
