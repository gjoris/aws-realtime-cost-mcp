"""RDS estimator tests against moto."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp.estimators import rds as rds_estimator
from aws_realtime_cost_mcp.estimators.rds import (
    ENGINE_DATABASE_NAMES,
    LOCATION_NAMES,
    PRICING_SERVICE_CODE,
    _instance_attrs,
    list_resources,
)


@pytest.fixture
def loaded_pricing(pricing, stub_pricing_loader):
    rows = [
        (
            _instance_attrs("db.t3.micro", "eu-west-1", "postgres", False),
            Decimal("0.018"),
        ),
        (
            _instance_attrs("db.m5.large", "eu-west-1", "mysql", True),
            Decimal("0.30"),
        ),
        (
            _instance_attrs("db.m5.large", "eu-west-1", "aurora-mysql", False),
            Decimal("0.29"),
        ),
    ]
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE, "eu-west-1", loader=stub_pricing_loader(rows)
    )
    return pricing


@mock_aws
def test_available_db_yields_resource(loaded_pricing):
    rds = boto3.client("rds", region_name="eu-west-1")
    rds.create_db_instance(
        DBInstanceIdentifier="prod-db",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="testpass123",
        AllocatedStorage=20,
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
    r = resources[0]
    assert r.service == "rds"
    assert r.resource_id == "prod-db"
    assert r.hourly_cost == Decimal("0.018")
    assert r.details["engine"] == "postgres"
    assert r.details["multi_az"] is False


@mock_aws
def test_multi_az_uses_multi_az_pricing(loaded_pricing):
    rds = boto3.client("rds", region_name="eu-west-1")
    rds.create_db_instance(
        DBInstanceIdentifier="ha-db",
        DBInstanceClass="db.m5.large",
        Engine="mysql",
        MasterUsername="admin",
        MasterUserPassword="testpass123",
        AllocatedStorage=100,
        MultiAZ=True,
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
    assert resources[0].hourly_cost == Decimal("0.30")
    assert resources[0].details["multi_az"] is True


@mock_aws
def test_creating_db_skipped_until_billable(loaded_pricing, monkeypatch):
    """A DB in 'creating' state shouldn't appear yet (not in _BILLABLE_STATES)."""
    rds = boto3.client("rds", region_name="eu-west-1")
    rds.create_db_instance(
        DBInstanceIdentifier="new-db",
        DBInstanceClass="db.t3.micro",
        Engine="postgres",
        MasterUsername="admin",
        MasterUserPassword="testpass123",
        AllocatedStorage=20,
    )

    real_describe = rds.describe_db_instances

    def force_creating(*args, **kwargs):
        result = real_describe(*args, **kwargs)
        for db in result["DBInstances"]:
            db["DBInstanceStatus"] = "creating"
        return result

    session = boto3.Session(region_name="eu-west-1")
    real_client = session.client

    def patched_client(name, **kw):
        c = real_client(name, **kw)
        if name == "rds":
            monkeypatch.setattr(c, "describe_db_instances", force_creating)
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
def test_unknown_pricing_falls_back_to_zero(loaded_pricing):
    rds = boto3.client("rds", region_name="eu-west-1")
    rds.create_db_instance(
        DBInstanceIdentifier="exotic-db",
        DBInstanceClass="db.r5.24xlarge",
        Engine="oracle-ee",
        MasterUsername="admin",
        MasterUserPassword="testpass123",
        AllocatedStorage=20,
        LicenseModel="bring-your-own-license",
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
    assert resources[0].hourly_cost == Decimal("0")


def test_engine_mapping_known_and_unknown():
    assert ENGINE_DATABASE_NAMES["mysql"] == "MySQL"
    attrs = _instance_attrs("db.t3.micro", "eu-west-1", "made-up-engine", False)
    assert attrs["databaseEngine"] == "made-up-engine"


def test_location_mapping_unknown_region_falls_through():
    attrs = _instance_attrs("db.t3.micro", "us-gov-west-1", "mysql", False)
    assert attrs["location"] == "us-gov-west-1"


def test_location_mapping_known_region():
    attrs = _instance_attrs("db.t3.micro", "eu-west-1", "mysql", False)
    assert attrs["location"] == LOCATION_NAMES["eu-west-1"]
