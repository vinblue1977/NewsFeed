"""Infrastructure tests: the stack synthesizes, passes cdk-nag, and keeps its buckets private."""

import functools
import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks

from infra.deploy_role import GITHUB_SUBJECT_PREFIX, DeployRoleStack
from infra.stack import NewsStack
from infra.tags import APP_TAGS

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
    template.has_resource_properties("AWS::Events::Rule", {"ScheduleExpression": "cron(0/15 * * * ? *)"})


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
    assert f"{GITHUB_SUBJECT_PREFIX}:ref:refs/heads/main" in trust
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Condition": {
                                        "StringEquals": Match.object_like(
                                            {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
                                        )
                                    }
                                }
                            )
                        ]
                    )
                }
            )
        },
    )
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


TAGGABLE = {
    "AWS::S3::Bucket",
    "AWS::Lambda::Function",
    "AWS::IAM::Role",
    "AWS::CloudFront::Distribution",
    "AWS::Logs::LogGroup",
    "AWS::Events::Rule",
    "AWS::IAM::OIDCProvider",
    "AWS::SSM::Parameter",
}
UNTAGGABLE_HELPER = "CustomS3AutoDeleteObjectsCustomResourceProvider"  # a raw CfnResource the Tags aspect does not reach


def test_app_tags_reach_every_taggable_resource() -> None:
    """The tags from infra.tags (which app.py applies) land on every taggable resource in both stacks."""
    app = cdk.App(context=CDK_CONTEXT)
    env = cdk.Environment(account=ACCOUNT, region="us-east-2")
    stacks = [NewsStack(app, "News", env=env), DeployRoleStack(app, "Role", env=env)]
    for key, value in APP_TAGS.items():
        cdk.Tags.of(app).add(key, value)
    for stack in stacks:
        for logical_id, res in Template.from_stack(stack).to_json()["Resources"].items():
            if logical_id.startswith(UNTAGGABLE_HELPER):
                continue
            has_tags_property = "Tags" in res.get("Properties", {})
            assert has_tags_property or res["Type"] not in TAGGABLE, f"{stack.stack_name}/{logical_id} is not tagged"
            if has_tags_property:
                tags = {t["Key"]: t["Value"] for t in res["Properties"]["Tags"]}
                assert APP_TAGS.items() <= tags.items(), f"{stack.stack_name}/{logical_id} lacks the app tags"


def test_a_failed_ingest_is_not_retried_by_lambda() -> None:
    template = _synthesized(ACCOUNT)[1]
    template.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_ingest_can_read_back_only_the_feed_object() -> None:
    template = _synthesized(ACCOUNT)[1]
    statements = [
        stmt
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
        if stmt["Action"] == "s3:GetObject"
    ]
    assert len(statements) == 1
    parts = statements[0]["Resource"]["Fn::Join"][1]
    assert parts[-1] == "/data/feed.json"  # bucket ARN + exactly this key, no wildcard


def test_headers_policy_has_permissions_policy_and_no_remote_images() -> None:
    template = _synthesized(ACCOUNT)[1]
    for policy in template.find_resources("AWS::CloudFront::ResponseHeadersPolicy").values():
        config = policy["Properties"]["ResponseHeadersPolicyConfig"]
        assert "img-src 'self';" in config["SecurityHeadersConfig"]["ContentSecurityPolicy"]["ContentSecurityPolicy"]
        names = {h["Header"] for h in config["CustomHeadersConfig"]["Items"]}
        assert {"Permissions-Policy", "Cross-Origin-Opener-Policy"} <= names


def test_story_pictures_expire_and_are_cached_long() -> None:
    template = _synthesized(ACCOUNT)[1]
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "LifecycleConfiguration": {
                "Rules": [Match.object_like({"Prefix": "data/img/", "ExpirationInDays": 3, "Status": "Enabled"})]
            }
        },
    )
    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {"CacheBehaviors": Match.array_with([Match.object_like({"PathPattern": "/data/img/*"})])}
            )
        },
    )
    csp = json.dumps(template.find_resources("AWS::CloudFront::ResponseHeadersPolicy"))
    assert "img-src 'self';" in csp  # pictures are our own copies; no publisher host is ever allowed
