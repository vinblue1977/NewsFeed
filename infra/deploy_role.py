"""The role GitHub Actions assumes (OIDC, no stored keys) to deploy the News stack.

It can do exactly one thing: assume this account's CDK bootstrap roles in the stack's region, and only for runs on `main`
of this repository. Deploy it once by hand (see README); after that CI uses it.
"""

from typing import Any

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_REPO = "vinblue1977/NewsFeed"
GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
QUALIFIER = "hnb659fds"  # the default CDK bootstrap qualifier
BOOTSTRAP_ROLES = ("deploy", "file-publishing", "image-publishing", "lookup")


class DeployRoleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # An account holds one OIDC provider per URL, and this account already has GitHub's: reference it, don't create it.
        provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self, "GitHub", self.format_arn(service="iam", region="", resource="oidc-provider", resource_name=GITHUB_OIDC_HOST)
        )
        role = iam.Role(
            self,
            "GitHubDeploy",
            description="GitHub Actions deploy for the News stack (assumes the CDK bootstrap roles only)",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(  # pyright: ignore[reportArgumentType]
                provider.open_id_connect_provider_arn,
                {
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
                        f"{GITHUB_OIDC_HOST}:sub": f"repo:{GITHUB_REPO}:ref:refs/heads/main",
                    }
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    self.format_arn(
                        service="iam",
                        region="",
                        resource="role",
                        resource_name=f"cdk-{QUALIFIER}-{kind}-role-{self.account}-{self.region}",
                    )
                    for kind in BOOTSTRAP_ROLES
                ],
            )
        )
        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
