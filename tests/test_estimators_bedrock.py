"""Bedrock estimator tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp.estimators import bedrock as bedrock_estimator
from aws_realtime_cost_mcp.estimators.bedrock import (
    LOCATION_NAMES,
    PRICING_SERVICE_CODE,
    _input_attrs,
    _output_attrs,
    list_resources,
)


@pytest.fixture
def loaded_pricing(pricing, stub_pricing_loader):
    rows = [
        (
            _input_attrs("eu-west-1", "anthropic.claude-sonnet-4-6"),
            Decimal("0.003"),
        ),
        (
            _output_attrs("eu-west-1", "anthropic.claude-sonnet-4-6"),
            Decimal("0.015"),
        ),
    ]
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE, "eu-west-1", loader=stub_pricing_loader(rows)
    )
    return pricing


@mock_aws
def test_active_model_yields_resource(loaded_pricing, monkeypatch):
    monkeypatch.setattr(
        bedrock_estimator,
        "_list_active_models",
        lambda session, region: ["anthropic.claude-sonnet-4-6"],
    )

    metrics = {
        "InputTokenCount": Decimal("100000"),
        "OutputTokenCount": Decimal("50000"),
    }

    def fake_sum(session, region, namespace, metric_name, dimensions, stat="Sum"):
        return metrics[metric_name]

    monkeypatch.setattr(
        bedrock_estimator.cloudwatch, "sum_over_last_hour", fake_sum
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
    assert r.resource_id == "anthropic.claude-sonnet-4-6"
    expected = (Decimal("100") * Decimal("0.003")) + (
        Decimal("50") * Decimal("0.015")
    )
    assert r.hourly_cost == expected


@mock_aws
def test_zero_traffic_model_skipped(loaded_pricing, monkeypatch):
    monkeypatch.setattr(
        bedrock_estimator,
        "_list_active_models",
        lambda session, region: ["anthropic.claude-sonnet-4-6"],
    )
    monkeypatch.setattr(
        bedrock_estimator.cloudwatch,
        "sum_over_last_hour",
        lambda *a, **kw: Decimal("0"),
    )

    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert resources == []


@mock_aws
def test_no_active_models_yields_nothing(loaded_pricing, monkeypatch):
    monkeypatch.setattr(
        bedrock_estimator, "_list_active_models", lambda session, region: []
    )
    resources = list(
        list_resources(
            boto3.Session(region_name="eu-west-1"),
            "eu-west-1",
            loaded_pricing,
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    assert resources == []


@mock_aws
def test_unknown_model_pricing_falls_back_to_zero(pricing, stub_pricing_loader, monkeypatch):
    pricing.ensure_loaded(
        PRICING_SERVICE_CODE,
        "eu-west-1",
        loader=stub_pricing_loader([({"unrelated": "x"}, Decimal("1"))]),
    )
    monkeypatch.setattr(
        bedrock_estimator, "_list_active_models", lambda session, region: ["unknown-model"]
    )

    monkeypatch.setattr(
        bedrock_estimator.cloudwatch,
        "sum_over_last_hour",
        lambda *a, **kw: Decimal("1000"),
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
    assert resources[0].details["input_tokens_last_hour"] == "1000"


@mock_aws
def test_list_active_models_via_cloudwatch():
    cw = boto3.client("cloudwatch", region_name="eu-west-1")
    cw.put_metric_data(
        Namespace="AWS/Bedrock",
        MetricData=[
            {
                "MetricName": "InputTokenCount",
                "Dimensions": [{"Name": "ModelId", "Value": "model-a"}],
                "Value": 1000,
            },
            {
                "MetricName": "InputTokenCount",
                "Dimensions": [{"Name": "ModelId", "Value": "model-b"}],
                "Value": 2000,
            },
            {
                "MetricName": "InputTokenCount",
                "Dimensions": [{"Name": "OtherDim", "Value": "x"}],
                "Value": 1,
            },
        ],
    )
    found = bedrock_estimator._list_active_models(
        boto3.Session(region_name="eu-west-1"), "eu-west-1"
    )
    assert sorted(found) == ["model-a", "model-b"]


def test_location_unknown_falls_through():
    assert _input_attrs("us-gov-west-1", "m")["location"] == "us-gov-west-1"


def test_location_known():
    assert _output_attrs("us-east-1", "m")["location"] == LOCATION_NAMES["us-east-1"]
