"""Cross-account session helpers via STS AssumeRole.

When `account_id` is None we use the default boto3 session (whatever the user
configured locally). When set, we assume into a reader role in that account
and cache the credentials for ~15 min so a batch of tool calls doesn't hammer
STS.

The role name is configurable via env var so customers can pick whatever name
their security team is comfortable rolling out via StackSet.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import boto3

DEFAULT_ROLE_NAME = "AWSRealtimeCostReader"
SESSION_TTL_SECONDS = 15 * 60


@dataclass
class _CachedSession:
    session: boto3.Session
    expires_at: float


_cache: dict[str, _CachedSession] = {}
_cache_lock = threading.Lock()


def role_name() -> str:
    return os.environ.get("AWS_REALTIME_COST_ROLE_NAME", DEFAULT_ROLE_NAME)


def get_session(account_id: Optional[str] = None) -> boto3.Session:
    """Return a boto3 Session for the given account.

    None → default session (caller's local credentials).
    Otherwise → assume `arn:aws:iam::<account_id>:role/<role_name>` and cache.
    """
    if account_id is None:
        return boto3.Session()

    now = time.time()
    with _cache_lock:
        cached = _cache.get(account_id)
        if cached and cached.expires_at > now:
            return cached.session

    sts = boto3.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name()}"
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="aws-realtime-cost-mcp",
        DurationSeconds=SESSION_TTL_SECONDS,
    )
    creds = response["Credentials"]
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    with _cache_lock:
        _cache[account_id] = _CachedSession(
            session=session,
            expires_at=now + SESSION_TTL_SECONDS - 60,
        )
    return session


def clear_cache() -> None:
    """Drop all cached assumed-role sessions. Used in tests."""
    with _cache_lock:
        _cache.clear()
