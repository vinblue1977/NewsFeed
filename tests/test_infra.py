"""Infrastructure tests: the stack synthesizes, passes cdk-nag, and keeps its buckets private."""

import functools
import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template
from cdk_nag import AwsSolutionsChecks

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
    props = [d["Properties"] for d in deployments.values()]
    manifest = next(p for p in props if p.get("DistributionPaths") == ["/manifest.webmanifest"])
    assert manifest["SystemMetadata"]["content-type"] == "application/manifest+json"
    assert manifest["Prune"] is False
    site = next(p for p in props if p is not manifest)
    assert "manifest.webmanifest" in site["Exclude"]  # excluded here, so it is neither guessed nor pruned
    assert any("DeploySite" in str(d) or "DeploySite" in k for k, d in deployments.items())
