"""Per-service cost estimators."""

from .base import Resource, Estimator
from . import ec2

ALL: dict[str, Estimator] = {
    ec2.SERVICE: ec2,
}

__all__ = ["Resource", "Estimator", "ALL"]
