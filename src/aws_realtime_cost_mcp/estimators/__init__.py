"""Per-service cost estimators."""

from .base import Resource, Estimator
from . import bedrock, ec2, nat, rds, sagemaker

ALL: dict[str, Estimator] = {
    ec2.SERVICE: ec2,
    rds.SERVICE: rds,
    sagemaker.SERVICE: sagemaker,
    nat.SERVICE: nat,
    bedrock.SERVICE: bedrock,
}

__all__ = ["Resource", "Estimator", "ALL"]
