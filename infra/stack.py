"""The News stack: a private site bucket and a private data bucket behind CloudFront, and a scheduled ingest Lambda.

No API, no auth, no user table: the app is static files plus feed JSON that the ingest Lambda writes to S3.
"""

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from cdk_nag import NagPackSuppression, NagSuppressions, RegexAppliesTo
from constructs import Construct

MANIFEST = "manifest.webmanifest"
DATA_PREFIX = "data"  # CloudFront serves the data bucket at /data/*
LOGS_POLICY = "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"


def _bucket(scope: Construct, construct_id: str, *, retain: bool = False) -> s3.Bucket:
    """Private, encrypted, TLS-only bucket. `retain` keeps the contents if the stack or construct is ever removed."""
    return s3.Bucket(
        scope,
        construct_id,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
        enforce_ssl=True,
        object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
        removal_policy=RemovalPolicy.RETAIN if retain else RemovalPolicy.DESTROY,
        auto_delete_objects=not retain,
    )


class NewsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        site_dir = str(self.node.try_get_context("siteDir") or "frontend/dist")

        site_bucket = _bucket(self, "SiteBucket")
        data_bucket = _bucket(self, "DataBucket", retain=True)  # feed JSON survives a replace or rename

        def headers_policy(construct_id: str, cache_control: str) -> cloudfront.ResponseHeadersPolicy:
            return cloudfront.ResponseHeadersPolicy(
                self,
                construct_id,
                security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                    content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                        content_security_policy=(
                            "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
                            "img-src 'self' data: https:; manifest-src 'self'; connect-src 'self'; worker-src 'self'; "
                            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
                            "upgrade-insecure-requests"
                        ),
                        override=True,
                    ),
                    strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                        access_control_max_age=Duration.days(365), include_subdomains=True, override=True
                    ),
                    content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                    frame_options=cloudfront.ResponseHeadersFrameOptions(
                        frame_option=cloudfront.HeadersFrameOption.DENY, override=True
                    ),
                    referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                        referrer_policy=cloudfront.HeadersReferrerPolicy.NO_REFERRER, override=True
                    ),
                ),
                custom_headers_behavior=cloudfront.ResponseCustomHeadersBehavior(
                    custom_headers=[
                        cloudfront.ResponseCustomHeader(header="X-Robots-Tag", value="noindex, nofollow", override=True),
                        cloudfront.ResponseCustomHeader(header="Cache-Control", value=cache_control, override=True),
                    ]
                ),
            )

        # index.html, the manifest and the data JSON must revalidate; Vite's content-hashed /assets/* never change.
        revalidate = headers_policy("SecurityHeaders", "no-cache")
        immutable = headers_policy("AssetHeaders", "public, max-age=31536000, immutable")
        # The feed is rewritten every 30 minutes: let the edge keep it for at most a few minutes.
        data_cache = cloudfront.CachePolicy(
            self,
            "DataCache",
            default_ttl=Duration.minutes(2),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.minutes(5),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )
        site_origin = origins.S3BucketOrigin.with_origin_access_control(site_bucket)  # pyright: ignore[reportArgumentType]
        distribution = cloudfront.Distribution(
            self,
            "Site",
            default_behavior=cloudfront.BehaviorOptions(
                origin=site_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=revalidate,
            ),
            additional_behaviors={
                "/assets/*": cloudfront.BehaviorOptions(
                    origin=site_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    response_headers_policy=immutable,
                ),
                f"/{DATA_PREFIX}/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(data_bucket),  # pyright: ignore[reportArgumentType]
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=data_cache,
                    response_headers_policy=revalidate,
                ),
            },
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )
        # The manifest gets an explicit content type (nosniff is on, so a guessed one could make browsers ignore it).
        site_deploy = s3deploy.BucketDeployment(
            self,
            "DeploySite",
            destination_bucket=site_bucket,
            sources=[s3deploy.Source.asset(site_dir)],
            exclude=[MANIFEST],
        )
        manifest_deploy = s3deploy.BucketDeployment(
            self,
            "DeployManifest",
            destination_bucket=site_bucket,
            sources=[s3deploy.Source.asset(site_dir)],
            exclude=["*"],
            include=[MANIFEST],
            content_type="application/manifest+json",
            prune=False,
            distribution=distribution,  # pyright: ignore[reportArgumentType]  # the one /* invalidation, after both uploads
        )
        manifest_deploy.node.add_dependency(site_deploy)  # one after the other, not in parallel

        # ---- scheduled ingest: EventBridge -> Lambda -> JSON in the data bucket (stub until Phase 2)
        fn = lambda_.Function(
            self,
            "Ingest",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            handler="ingest.handler.handler",
            code=lambda_.Code.from_asset("backend", exclude=["**/__pycache__"]),
            memory_size=256,
            timeout=Duration.seconds(60),
            environment={"DATA_BUCKET": data_bucket.bucket_name, "DATA_PREFIX": DATA_PREFIX},
            log_group=logs.LogGroup(self, "IngestLogs", retention=logs.RetentionDays.TWO_WEEKS),
        )
        data_bucket.grant_put(fn, f"{DATA_PREFIX}/*")  # pyright: ignore[reportArgumentType]
        events.Rule(
            self,
            "IngestSchedule",
            schedule=events.Schedule.rate(Duration.minutes(30)),
            targets=[targets.LambdaFunction(fn)],  # pyright: ignore[reportArgumentType]
        )

        CfnOutput(self, "SiteUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "DataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "IngestFunction", value=fn.function_name)

        # ---- cdk-nag suppressions, each with its reason
        def reason(rule: str, why: str, applies_to: list | None = None) -> NagPackSuppression:
            return NagPackSuppression(id=rule, reason=why, applies_to=applies_to)

        NagSuppressions.add_resource_suppressions(
            distribution,
            [
                reason("AwsSolutions-CFR1", "Personal app; no geo restriction needed"),
                reason("AwsSolutions-CFR2", "WAF costs ~$5+/month, over the $0.15 budget; public data only, no user input"),
                reason("AwsSolutions-CFR3", "Access logs cost extra; CloudFront metrics suffice for a personal app"),
                reason("AwsSolutions-CFR4", "Default CloudFront domain and certificate (no custom domain yet)"),
            ],
        )
        NagSuppressions.add_resource_suppressions(
            site_bucket, [reason("AwsSolutions-S1", "Static app files; access logging costs extra")]
        )
        NagSuppressions.add_resource_suppressions(
            data_bucket, [reason("AwsSolutions-S1", "Public news JSON; access logging costs extra")]
        )
        NagSuppressions.add_resource_suppressions(
            fn,
            [
                reason("AwsSolutions-IAM4", "Basic execution role only writes this function's logs", [LOGS_POLICY]),
                reason(
                    "AwsSolutions-IAM5",
                    "Write access is limited to the data/ prefix of one bucket",
                    [RegexAppliesTo(regex=r"/^Resource::.*/data/\*$/g"), RegexAppliesTo(regex=r"/^Action::s3:Abort\*$/g")],
                ),
            ],
            apply_to_children=True,
        )
        # CDK's own helper Lambdas (bucket deployment, auto-delete, log retention) are the "Custom::*" and
        # "LogRetention*" children of the stack. Suppress only on those, so the Ingest function and everything of ours
        # stays checked. A CDK upgrade that adds a helper with another prefix fails cdk-nag in CI (fails closed);
        # then add the prefix to the list below.
        for child in self.node.children:
            if child.node.id.startswith(("Custom::", "LogRetention")):
                NagSuppressions.add_resource_suppressions(
                    child,
                    [
                        reason("AwsSolutions-IAM4", "CDK-managed helper Lambda uses the basic execution role", [LOGS_POLICY]),
                        reason(
                            "AwsSolutions-IAM5",
                            "CDK bucket deployment needs object-level wildcards on its own buckets",
                            [RegexAppliesTo(regex=r"/^(Action::s3:.*|Resource::.*\*)$/g")],
                        ),
                        reason("AwsSolutions-L1", "CDK-managed helper Lambda picks its own runtime"),
                    ],
                    apply_to_children=True,
                )
