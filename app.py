#!/usr/bin/env python3
"""CDK entry point. `cdk synth` also runs cdk-nag's AWS Solutions security checks."""

import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from infra.deploy_role import DeployRoleStack
from infra.stack import NewsStack

app = cdk.App()
NewsStack(
    app,
    "News",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="us-east-2",  # placeholder: fixed, because the CDK CLI defaults to us-east-1 without credentials
    ),
    termination_protection=True,
    description="Personal iPhone-first news PWA: scheduled feed ingest to S3, served by CloudFront",
)
DeployRoleStack(
    app,
    "NewsDeployRole",
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-2"),
    termination_protection=True,
    description="GitHub Actions OIDC deploy role for the News stack (deployed once by hand)",
)
cdk.Tags.of(app).add("project", "news")
cdk.Tags.of(app).add("managed-by", "cdk")
cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
app.synth()
