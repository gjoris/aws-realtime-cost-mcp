"""SageMaker estimator tests against moto."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp.estimators.sagemaker import (
    LOCATION_NAMES,
    PRICING_SERVICE_CODE,
    _instance_attrs,
    list_resources,
)


@pytest.fixture
def loaded_pricing(pricing, stub_pricing_loader):
    rows = [
        (_instance_attrs("ml.m5.large", "eu-west-1"), Decimal("0.140")),
        (_instance_attrs("ml.g4dn.xlarge", "eu-west-1"), Decimal("1.50")),
    ]
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE, "eu-west-1", loader=stub_pricing_loader(rows)
    )
    return pricing


def _create_endpoint(client, name: str, instance_type: str, count: int = 1):
    client.create_model(
        ModelName=f"{name}-model",
        PrimaryContainer={"Image": "12345.dkr.ecr.eu-west-1.amazonaws.com/x:latest"},
        ExecutionRoleArn="arn:aws:iam::123456789012:role/SMRole",
    )
    client.create_endpoint_config(
        EndpointConfigName=f"{name}-config",
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": f"{name}-model",
                "InitialInstanceCount": count,
                "InstanceType": instance_type,
            }
        ],
    )
    client.create_endpoint(
        EndpointName=name, EndpointConfigName=f"{name}-config"
    )


@mock_aws
def test_in_service_endpoint_yields_resource(loaded_pricing):
    sm = boto3.client("sagemaker", region_name="eu-west-1")
    _create_endpoint(sm, "demo", "ml.m5.large", count=1)

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
    assert r.service == "sagemaker"
    assert r.resource_id == "demo"
    assert r.hourly_cost == Decimal("0.140")
    assert r.details["variants"][0]["instance_type"] == "ml.m5.large"


@mock_aws
def test_endpoint_with_multiple_instances_multiplies(loaded_pricing):
    sm = boto3.client("sagemaker", region_name="eu-west-1")
    _create_endpoint(sm, "scaled", "ml.g4dn.xlarge", count=3)

    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert len(resources) == 1
    assert resources[0].hourly_cost == Decimal("4.50")
    assert resources[0].details["variants"][0]["instance_count"] == 3


@mock_aws
def test_creating_endpoint_skipped(loaded_pricing, monkeypatch):
    sm = boto3.client("sagemaker", region_name="eu-west-1")
    _create_endpoint(sm, "warming-up", "ml.m5.large", count=1)

    real_list = sm.list_endpoints

    def force_creating(*args, **kwargs):
        result = real_list(*args, **kwargs)
        for ep in result["Endpoints"]:
            ep["EndpointStatus"] = "Creating"
        return result

    session = boto3.Session(region_name="eu-west-1")
    real_client = session.client

    def patched_client(name, **kw):
        c = real_client(name, **kw)
        if name == "sagemaker":
            monkeypatch.setattr(c, "list_endpoints", force_creating)
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
    sm = boto3.client("sagemaker", region_name="eu-west-1")
    _create_endpoint(sm, "exotic", "ml.p2.16xlarge", count=1)

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


@mock_aws
def test_variant_without_instance_type_skipped(loaded_pricing):
    """Defensive: SageMaker docs allow InstanceType to be absent for serverless."""
    sm = boto3.client("sagemaker", region_name="eu-west-1")
    sm.create_model(
        ModelName="serverless-model",
        PrimaryContainer={"Image": "12345.dkr.ecr.eu-west-1.amazonaws.com/x:latest"},
        ExecutionRoleArn="arn:aws:iam::123456789012:role/SMRole",
    )
    sm.create_endpoint_config(
        EndpointConfigName="serverless-config",
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": "serverless-model",
                "ServerlessConfig": {"MemorySizeInMB": 2048, "MaxConcurrency": 5},
            }
        ],
    )
    sm.create_endpoint(
        EndpointName="serverless", EndpointConfigName="serverless-config"
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
    assert resources[0].details["variants"] == []


def test_location_mapping_unknown_region_falls_through():
    attrs = _instance_attrs("ml.m5.large", "us-gov-west-1")
    assert attrs["location"] == "us-gov-west-1"


def test_location_mapping_known_region():
    attrs = _instance_attrs("ml.m5.large", "us-east-1")
    assert attrs["location"] == LOCATION_NAMES["us-east-1"]
