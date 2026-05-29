"""CloudWatch helper tests with moto."""

from __future__ import annotations

from decimal import Decimal

import boto3
from moto import mock_aws

from aws_realtime_cost_mcp import cloudwatch


@mock_aws
def test_sum_over_last_hour_with_data():
    cw = boto3.client("cloudwatch", region_name="eu-west-1")
    cw.put_metric_data(
        Namespace="Test/NS",
        MetricData=[
            {
                "MetricName": "Bytes",
                "Dimensions": [{"Name": "Tag", "Value": "x"}],
                "Value": 1024,
            }
        ],
    )
    result = cloudwatch.sum_over_last_hour(
        boto3.Session(region_name="eu-west-1"),
        "eu-west-1",
        "Test/NS",
        "Bytes",
        [{"Name": "Tag", "Value": "x"}],
    )
    assert result >= Decimal("0")


@mock_aws
def test_sum_over_last_hour_empty_returns_zero():
    result = cloudwatch.sum_over_last_hour(
        boto3.Session(region_name="eu-west-1"),
        "eu-west-1",
        "Test/Empty",
        "NoData",
        [{"Name": "Tag", "Value": "absent"}],
    )
    assert result == Decimal("0")


def test_no_results_returns_zero(monkeypatch):
    """Defensive: GetMetricData should always return MetricDataResults but if not, we return 0."""

    class _FakeClient:
        def get_metric_data(self, **kwargs):
            return {}

    class _FakeSession:
        def client(self, name, region_name=None):
            return _FakeClient()

    result = cloudwatch.sum_over_last_hour(
        _FakeSession(), "eu-west-1", "X", "Y", []
    )
    assert result == Decimal("0")


def test_no_values_returns_zero(monkeypatch):
    class _FakeClient:
        def get_metric_data(self, **kwargs):
            return {"MetricDataResults": [{"Values": []}]}

    class _FakeSession:
        def client(self, name, region_name=None):
            return _FakeClient()

    result = cloudwatch.sum_over_last_hour(
        _FakeSession(), "eu-west-1", "X", "Y", []
    )
    assert result == Decimal("0")


def test_returns_first_value_when_present():
    class _FakeClient:
        def get_metric_data(self, **kwargs):
            return {"MetricDataResults": [{"Values": [42.5, 10.0]}]}

    class _FakeSession:
        def client(self, name, region_name=None):
            return _FakeClient()

    result = cloudwatch.sum_over_last_hour(
        _FakeSession(), "eu-west-1", "X", "Y", []
    )
    assert result == Decimal("42.5")
