"""Cross-account auth tests using moto for STS."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from aws_realtime_cost_mcp import auth


def test_get_session_no_account_returns_default(monkeypatch):
    session = auth.get_session(None)
    assert isinstance(session, boto3.Session)


@mock_aws
def test_get_session_assumes_role():
    session = auth.get_session("123456789012")
    assert isinstance(session, boto3.Session)
    creds = session.get_credentials()
    assert creds.access_key
    assert creds.secret_key


@mock_aws
def test_get_session_caches_per_account():
    s1 = auth.get_session("111111111111")
    s2 = auth.get_session("111111111111")
    assert s1 is s2

    s3 = auth.get_session("222222222222")
    assert s3 is not s1


def test_role_name_default(monkeypatch):
    monkeypatch.delenv("AWS_REALTIME_COST_ROLE_NAME", raising=False)
    assert auth.role_name() == auth.DEFAULT_ROLE_NAME


def test_role_name_override(monkeypatch):
    monkeypatch.setenv("AWS_REALTIME_COST_ROLE_NAME", "CustomRole")
    assert auth.role_name() == "CustomRole"


@mock_aws
def test_get_session_refreshes_after_expiry(monkeypatch):
    s1 = auth.get_session("333333333333")

    monkeypatch.setattr(
        auth, "_cache", {k: auth._CachedSession(v.session, 0) for k, v in auth._cache.items()}
    )

    s2 = auth.get_session("333333333333")
    assert s2 is not s1
