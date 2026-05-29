"""Per-service cost estimators."""

from .base import Resource, Estimator
from . import ec2, rds, sagemaker

ALL: dict[str, Estimator] = {
    ec2.SERVICE: ec2,
    rds.SERVICE: rds,
    sagemaker.SERVICE: sagemaker,
}

__all__ = ["Resource", "Estimator", "ALL"]
