"""PaperTrail AWS stack: VPC, RDS Postgres (pgvector), ECS Fargate MCP server behind an HTTPS ALB, S3, Cognito,
Textract/Bedrock IAM, and a daily EventBridge Scheduler -> Fargate reminder task that emails via SES.

Deploy (from infra/):  npx aws-cdk@2 deploy -c domain_name=... -c hosted_zone_id=... -c hosted_zone_name=... \
    -c alert_email=... -c ses_from=... -c extract_model_id=... -c qa_model_id=...
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration, RemovalPolicy, Stack,
    aws_budgets as budgets,
    aws_certificatemanager as acm,
    aws_cognito as cognito,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_rds as rds,
    aws_route53 as route53,
    aws_s3 as s3,
    aws_scheduler as scheduler,
    aws_scheduler_targets as targets,
    aws_ses as ses,
)
from aws_cdk.aws_ecr_assets import Platform
from constructs import Construct

ROOT = str(Path(__file__).resolve().parent.parent)
INSPECTOR_CALLBACKS = ["http://localhost:6274/oauth/callback", "http://localhost:6274/oauth/callback/debug"]


class PaperTrailStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(scope, id, **kwargs)
        ctx = self.node.get_context
        domain_name: str = ctx("domain_name")
        canonical_uri = f"https://{domain_name}/mcp"

        # ponytail: no NAT gateway (~$32/month). Tasks sit in public subnets with public IPs; RDS stays isolated.
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0, subnet_configuration=[
            ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC),
            ec2.SubnetConfiguration(name="db", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        ])
        public = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)

        db = rds.DatabaseInstance(
            self, "Db",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_17),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO),
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            credentials=rds.Credentials.from_generated_secret("papertrail"), database_name="papertrail",
            allocated_storage=20, storage_encrypted=True, backup_retention=Duration.days(1),
            removal_policy=RemovalPolicy.DESTROY, deletion_protection=False, delete_automated_backups=True,
        )
        assert db.secret

        bucket = s3.Bucket(
            self, "Docs", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
        )

        pool = cognito.UserPool(
            self, "Users", self_sign_up_enabled=False, sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True), removal_policy=RemovalPolicy.DESTROY,
        )
        auth_domain = pool.add_domain("Domain", cognito_domain=cognito.CognitoDomainOptions(
            domain_prefix=self.node.try_get_context("cognito_prefix") or f"papertrail-{self.account}",
        ))
        # Public client (no secret), authorization code + PKCE. Phase 5 adds the Alexa redirect URLs.
        app_client = pool.add_client(
            "McpClient", generate_secret=False, prevent_user_existence_errors=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=INSPECTOR_CALLBACKS + (self.node.try_get_context("extra_callbacks") or []),
            ),
        )

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=ctx("hosted_zone_id"), zone_name=ctx("hosted_zone_name"),
        )
        cert = acm.Certificate(self, "Cert", domain_name=domain_name, validation=acm.CertificateValidation.from_dns(zone))

        image = ecs.ContainerImage.from_asset(ROOT, platform=Platform.LINUX_AMD64)
        environment = {
            "COGNITO_USER_POOL_ID": pool.user_pool_id,
            "COGNITO_CLIENT_ID": app_client.user_pool_client_id,
            "MCP_CANONICAL_URI": canonical_uri,
            "S3_BUCKET": bucket.bucket_name,
            "DB_HOST": db.db_instance_endpoint_address,
            "DB_PORT": db.db_instance_endpoint_port,
            "BEDROCK_EXTRACT_MODEL_ID": self.node.try_get_context("extract_model_id") or "",
            "BEDROCK_QA_MODEL_ID": self.node.try_get_context("qa_model_id") or "",
            "BEDROCK_EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0",
            "SES_FROM": ctx("ses_from"),
            "DEMO_USER_ID": self.node.try_get_context("demo_user_id") or "demo",
        }
        secrets = {
            "DB_USER": ecs.Secret.from_secrets_manager(db.secret, "username"),
            "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, "password"),
        }

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Mcp", vpc=vpc, cpu=512, memory_limit_mib=1024, desired_count=1,
            task_subnets=public, assign_public_ip=True, public_load_balancer=True,
            protocol=elbv2.ApplicationProtocol.HTTPS, certificate=cert, redirect_http=True,
            domain_name=domain_name, domain_zone=zone,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image, container_port=8000, environment=environment, secrets=secrets,
            ),
        )
        service.target_group.configure_health_check(path="/healthz")
        db.connections.allow_default_port_from(service.service)

        reminder_task = ecs.FargateTaskDefinition(self, "ReminderTask", cpu=256, memory_limit_mib=512)
        reminder_task.add_container(
            "reminders", image=image, command=["python", "-m", "reminders.handler"],
            environment=environment, secrets=secrets,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="reminders"),
        )
        reminder_sg = ec2.SecurityGroup(self, "ReminderSg", vpc=vpc)
        db.connections.allow_default_port_from(reminder_sg)
        scheduler.Schedule(
            self, "DailyReminders",
            schedule=scheduler.ScheduleExpression.cron(hour="3", minute="30"),  # 09:00 IST
            target=targets.EcsRunFargateTask(
                service.cluster, task_definition=reminder_task, assign_public_ip=True,
                vpc_subnets=public, security_groups=[reminder_sg],
            ),
        )

        for role in (service.task_definition.task_role, reminder_task.task_role):
            role.add_to_principal_policy(iam.PolicyStatement(
                actions=["textract:AnalyzeDocument", "bedrock:InvokeModel", "ses:SendEmail"], resources=["*"],
            ))
            role.add_to_principal_policy(iam.PolicyStatement(actions=["cognito-idp:ListUsers"],
                                                             resources=[pool.user_pool_arn]))
            bucket.grant_read_write(role)

        ses.EmailIdentity(self, "Sender", identity=ses.Identity.email(ctx("ses_from")))

        budgets.CfnBudget(self, "Budget", budget=budgets.CfnBudget.BudgetDataProperty(
            budget_type="COST", time_unit="MONTHLY",
            budget_limit=budgets.CfnBudget.SpendProperty(amount=float(self.node.try_get_context("budget_usd") or 30), unit="USD"),
        ), notifications_with_subscribers=[budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                comparison_operator="GREATER_THAN", notification_type="ACTUAL", threshold=80, threshold_type="PERCENTAGE",
            ),
            subscribers=[budgets.CfnBudget.SubscriberProperty(address=ctx("alert_email"), subscription_type="EMAIL")],
        )])

        for name, value in {
            "McpUrl": canonical_uri,
            "UserPoolId": pool.user_pool_id,
            "ClientId": app_client.user_pool_client_id,
            "AuthDomain": auth_domain.base_url(),
            "ClusterName": service.cluster.cluster_name,
            "TaskDefinition": service.task_definition.family,
            "TaskSecurityGroup": service.service.connections.security_groups[0].security_group_id,
            "PublicSubnets": ",".join(s.subnet_id for s in vpc.public_subnets),
            "Bucket": bucket.bucket_name,
        }.items():
            cdk.CfnOutput(self, name, value=value)


app = cdk.App()
PaperTrailStack(app, "PaperTrail", env=cdk.Environment(
    account=app.node.try_get_context("account"), region=app.node.try_get_context("region") or "us-east-1",
))
app.synth()
