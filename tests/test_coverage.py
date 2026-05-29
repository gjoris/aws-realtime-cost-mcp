"""Coverage report tests using moto."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp import coverage as coverage_mod


@mock_aws
def test_report_with_no_uncovered_resources():
    result = coverage_mod.report(None, "eu-west-1")
    assert "ec2" in result["covered_services"]
    assert "rds" in result["covered_services"]
    assert "sagemaker" in result["covered_services"]
    assert "nat_gateway" in result["covered_services"]
    assert "bedrock" in result["covered_services"]
    assert result["region"] == "eu-west-1"
    assert result["unmeasured_running_services"] == []


@mock_aws
def test_report_flags_running_opensearch():
    client = boto3.client("opensearch", region_name="eu-west-1")
    client.create_domain(DomainName="logs", EngineVersion="OpenSearch_2.11")

    result = coverage_mod.report(None, "eu-west-1")
    services = [u["service"] for u in result["unmeasured_running_services"]]
    assert "opensearch" in services


@mock_aws
def test_report_flags_running_elasticache():
    client = boto3.client("elasticache", region_name="eu-west-1")
    client.create_cache_cluster(
        CacheClusterId="cache",
        CacheNodeType="cache.t3.micro",
        Engine="redis",
        NumCacheNodes=1,
    )
    result = coverage_mod.report(None, "eu-west-1")
    services = [u["service"] for u in result["unmeasured_running_services"]]
    assert "elasticache" in services


@mock_aws
def test_report_flags_redshift():
    client = boto3.client("redshift", region_name="eu-west-1")
    client.create_cluster(
        ClusterIdentifier="dw",
        NodeType="dc2.large",
        MasterUsername="admin",
        MasterUserPassword="Test1234",
        DBName="dev",
    )
    result = coverage_mod.report(None, "eu-west-1")
    services = [u["service"] for u in result["unmeasured_running_services"]]
    assert "redshift" in services


@mock_aws
def test_report_flags_neptune():
    client = boto3.client("neptune", region_name="eu-west-1")
    client.create_db_cluster(
        DBClusterIdentifier="graph", Engine="neptune"
    )
    result = coverage_mod.report(None, "eu-west-1")
    services = [u["service"] for u in result["unmeasured_running_services"]]
    assert "neptune" in services


@mock_aws
def test_report_flags_msk():
    client = boto3.client("kafka", region_name="eu-west-1")
    client.create_cluster_v2(
        ClusterName="stream",
        Provisioned={
            "BrokerNodeGroupInfo": {
                "InstanceType": "kafka.t3.small",
                "ClientSubnets": ["subnet-1234"],
            },
            "KafkaVersion": "3.7.x",
            "NumberOfBrokerNodes": 2,
        },
    )
    result = coverage_mod.report(None, "eu-west-1")
    services = [u["service"] for u in result["unmeasured_running_services"]]
    assert "msk" in services
