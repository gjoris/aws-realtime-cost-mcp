"""Detect AWS services that are running but not covered by an estimator.

This is the user-honesty layer of the server: a $50/h estimate is dangerous
if there's an unmeasured $500/h OpenSearch cluster running. We do cheap
discovery calls to known-expensive services we DON'T have estimators for and
flag their presence.
"""

from __future__ import annotations

from typing import Any

from . import auth
from .estimators import ALL as ESTIMATORS


def _check_opensearch(session: Any, region: str) -> int:
    client = session.client("opensearch", region_name=region)
    return len(client.list_domain_names().get("DomainNames", []))


def _check_elasticache(session: Any, region: str) -> int:
    client = session.client("elasticache", region_name=region)
    return len(
        client.describe_cache_clusters().get("CacheClusters", [])
    )


def _check_msk(session: Any, region: str) -> int:
    client = session.client("kafka", region_name=region)
    paginator = client.get_paginator("list_clusters_v2")
    count = 0
    for page in paginator.paginate():
        count += len(page.get("ClusterInfoList", []))
    return count


def _check_redshift(session: Any, region: str) -> int:
    client = session.client("redshift", region_name=region)
    return len(client.describe_clusters().get("Clusters", []))


def _check_neptune(session: Any, region: str) -> int:
    client = session.client("neptune", region_name=region)
    return len(client.describe_db_clusters().get("DBClusters", []))


_UNCOVERED_PROBES: dict[str, callable] = {
    "opensearch": _check_opensearch,
    "elasticache": _check_elasticache,
    "msk": _check_msk,
    "redshift": _check_redshift,
    "neptune": _check_neptune,
}


def report(account_id: str | None, region: str) -> dict[str, Any]:
    """Return a coverage report: covered estimators + any uncovered services that have running resources."""
    session = auth.get_session(account_id)
    covered = sorted(ESTIMATORS.keys())
    unmeasured: list[dict[str, Any]] = []
    for name, probe in _UNCOVERED_PROBES.items():
        try:
            count = probe(session, region)
        except Exception as e:  # pragma: no cover
            unmeasured.append({"service": name, "error": str(e)})
            continue
        if count > 0:
            unmeasured.append({"service": name, "resource_count": count})
    return {
        "region": region,
        "covered_services": covered,
        "unmeasured_running_services": unmeasured,
    }
