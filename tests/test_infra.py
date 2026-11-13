"""Infrastructure tests: the stack synthesizes, passes cdk-nag, and keeps its buckets private."""

import functools
import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks

from infra.deploy_role import DeployRoleStack
from infra.stack import NewsStack

# The same feature flags as a real synth, so tests render the template the way a deploy does.
CDK_CONTEXT = {k: v for k, v in json.loads(Path("cdk.json").read_text())["context"].items() if k.startswith("@")}
CDK_CONTEXT["siteDir"] = "tests/fixtures/site"  # a stand-in app, so tests don't need a frontend build


ACCOUNT = "123456789012"  # the docs example account


@functools.cache
def _synthesized(account: str | None) -> tuple[NewsStack, Template]:
    """Synthesizing is the slow part of these tests, so build each variant once."""
    app = cdk.App(context=CDK_CONTEXT)
    stack = NewsStack(app, "News", env=cdk.Environment(account=account, region="us-east-2"))
    cdk.Aspects.of(app).add(AwsSolutionsChecks())
    return stack, Template.from_stack(stack)


@pytest.mark.parametrize("account", [ACCOUNT, None])  # None: CI synth without AWS credentials
def test_no_cdk_nag_findings(account: str | None) -> None:
    stack, _ = _synthesized(account)  # synthesizing runs the aspects
    annotations = Annotations.from_stack(stack)
    assert annotations.find_error("*", Match.string_like_regexp("AwsSolutions-.*")) == []
    assert annotations.find_warning("*", Match.string_like_regexp("AwsSolutions-.*")) == []


def test_buckets_are_private() -> None:
    template = _synthesized(ACCOUNT)[1]
    buckets = template.find_resources("AWS::S3::Bucket")
    assert len(buckets) == 2
    for bucket in buckets.values():
        assert bucket["Properties"]["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }


def test_ingest_runs_on_a_schedule() -> None:
    template = _synthesized(ACCOUNT)[1]
    template.has_resource_properties("AWS::Events::Rule", {"ScheduleExpression": "rate(30 minutes)"})


def test_data_bucket_is_retained_and_site_bucket_is_not() -> None:
    template = _synthesized(ACCOUNT)[1]
    policies = {r["DeletionPolicy"] for r in template.find_resources("AWS::S3::Bucket").values()}
    assert policies == {"Retain", "Delete"}  # feed JSON survives a replace; the site bucket is rebuilt from the app


def test_data_is_cached_briefly_and_assets_are_immutable() -> None:
    template = _synthesized(ACCOUNT)[1]
    template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {"CachePolicyConfig": Match.object_like({"DefaultTTL": 120, "MaxTTL": 300})},
    )
    immutable = json.dumps(template.find_resources("AWS::CloudFront::ResponseHeadersPolicy"))
    assert "public, max-age=31536000, immutable" in immutable
    assert immutable.count('"no-cache"') == 1  # index.html and data revalidate, /assets/* does not


def test_csp_allows_a_service_worker_but_no_inline_styles() -> None:
    template = _synthesized(ACCOUNT)[1]
    csp = json.dumps(template.find_resources("AWS::CloudFront::ResponseHeadersPolicy"))
    assert "worker-src 'self'" in csp
    assert "unsafe-inline" not in csp


def test_manifest_is_deployed_separately_with_its_content_type() -> None:
    template = _synthesized(ACCOUNT)[1]
    deployments = template.find_resources("Custom::CDKBucketDeployment")
    assert len(deployments) == 2
    site = next(v["Properties"] for k, v in deployments.items() if k.startswith("DeploySite"))
    manifest = next(v["Properties"] for k, v in deployments.items() if k.startswith("DeployManifest"))
    assert "manifest.webmanifest" in site["Exclude"]  # not uploaded (or pruned) by the site deployment
    assert "content-type" not in site.get("SystemMetadata", {})
    assert manifest["Include"] == ["manifest.webmanifest"]
    assert manifest["SystemMetadata"]["content-type"] == "application/manifest+json"
    assert manifest["Prune"] is False
    assert "DistributionId" not in site  # a single /* invalidation, from the manifest deployment
    assert "DistributionId" in manifest


def test_ingest_reads_only_the_location_parameter_and_logs_for_a_week() -> None:
    template = _synthesized(ACCOUNT)[1]
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 7})
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Environment": {"Variables": Match.object_like({"LOCATION_PARAM": "/news/location"})}},
    )
    policies = json.dumps(template.find_resources("AWS::IAM::Policy"))
    assert '"ssm:GetParameter"' in policies
    assert "parameter/news/location" in policies
    assert "ssm:*" not in policies


def _deploy_role_template() -> tuple[DeployRoleStack, Template]:
    app = cdk.App(context=CDK_CONTEXT)
    stack = DeployRoleStack(app, "NewsDeployRole", env=cdk.Environment(account=ACCOUNT, region="us-east-2"))
    cdk.Aspects.of(app).add(AwsSolutionsChecks())
    return stack, Template.from_stack(stack)


def test_deploy_role_passes_cdk_nag() -> None:
    stack, _ = _deploy_role_template()
    annotations = Annotations.from_stack(stack)
    assert annotations.find_error("*", Match.string_like_regexp("AwsSolutions-.*")) == []
    assert annotations.find_warning("*", Match.string_like_regexp("AwsSolutions-.*")) == []


def test_deploy_role_trusts_only_main_of_this_repo_and_only_assumes_bootstrap_roles() -> None:
    template = _deploy_role_template()[1]
    trust = json.dumps(template.find_resources("AWS::IAM::Role"))
    assert "repo:vinblue1977/NewsFeed:ref:refs/heads/main" in trust
    assert "sts.amazonaws.com" in trust
    assert "*" not in json.dumps(template.find_resources("AWS::IAM::Policy"))  # no wildcards anywhere in the permissions
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": [
                    {
                        "Action": "sts:AssumeRole",
                        "Effect": "Allow",
                        "Resource": Match.array_with(
                            [Match.string_like_regexp(r"role/cdk-hnb659fds-deploy-role-123456789012-us-east-2$")]
                        ),
                    }
                ],
                "Version": "2012-10-17",
            }
        },
    )
