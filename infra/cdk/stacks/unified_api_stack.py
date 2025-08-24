from pathlib import Path
from typing import Optional

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_s3 as s3,
    aws_events as events,
    aws_events_targets as targets,
    aws_cloudwatch as cw,
)
from constructs import Construct


class UnifiedApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env: Optional[cdk.Environment] = None, **kwargs) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        # Parameters
        db_host = cdk.CfnParameter(self, "DbHost", type="String", default="postgres", description="Database host")
        db_name = cdk.CfnParameter(self, "DbName", type="String", default="pqfile_db")
        db_user = cdk.CfnParameter(self, "DbUser", type="String", default="postgres")
        db_password = cdk.CfnParameter(self, "DbPassword", type="String", no_echo=True, default="postgres")
        s3_bucket_name = cdk.CfnParameter(self, "DocumentsBucketName", type="String", default="documents")
        min_active_keys_param = cdk.CfnParameter(self, "MinActiveKeys", type="Number", default=3)

        # S3 bucket (optional: use existing if provided)
        bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            bucket_name=s3_bucket_name.value_as_string,
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Lambda function code from existing source dir
        lambda_src_dir = Path(__file__).resolve().parents[3] / "lambdas" / "unified_api"

        fn = _lambda.Function(
            self,
            "UnifiedApiFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="app.lambda_handler",
            code=_lambda.Code.from_asset(str(lambda_src_dir)),
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "DB_HOST": db_host.value_as_string,
                "DB_NAME": db_name.value_as_string,
                "DB_USER": db_user.value_as_string,
                "DB_PASSWORD": db_password.value_as_string,
                "S3_BUCKET": bucket.bucket_name,
                # Region is provided by Lambda runtime; do not set AWS_REGION manually
            },
        )

        # Permissions: S3 access (read/write)
        bucket.grant_read_write(fn)

        # KMS: Allow key creation and usage as per your backup/rotation design
        # Narrow KMS permissions to what the function actually needs
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kms:CreateKey",
                    "kms:DescribeKey",
                    "kms:TagResource",
                    "kms:Encrypt",
                    "kms:Decrypt",
                ],
                resources=["*"],
            )
        )

        # API Gateway
        api = apigw.RestApi(
            self,
            "UnifiedApiGateway",
            rest_api_name="PQFile Unified API",
            deploy_options=apigw.StageOptions(throttling_rate_limit=50, throttling_burst_limit=100),
        )

        # /encrypt (POST)
        encrypt_res = api.root.add_resource("encrypt")
        encrypt_integration = apigw.LambdaIntegration(fn, proxy=True)
        encrypt_res.add_method("POST", encrypt_integration)

        # /decrypt/{document_id} (GET)
        decrypt_res = api.root.add_resource("decrypt").add_resource("{document_id}")
        decrypt_integration = apigw.LambdaIntegration(fn, proxy=True)
        decrypt_res.add_method("GET", decrypt_integration)

        # Rotation Lambda (EventBridge monthly)
        rotate_fn = _lambda.Function(
            self,
            "RotateKeysFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="app.lambda_handler",
            code=_lambda.Code.from_asset(str(Path(__file__).resolve().parents[3] / "lambdas" / "rotate_keys")),
            timeout=Duration.seconds(300),
            memory_size=1024,
            environment={
                "DB_HOST": db_host.value_as_string,
                "DB_NAME": db_name.value_as_string,
                "DB_USER": db_user.value_as_string,
                "DB_PASSWORD": db_password.value_as_string,
                # Region is provided by Lambda runtime; do not set AWS_REGION manually
                "S3_BUCKET": bucket.bucket_name,
                "ROTATE_AGE_DAYS": "30",
                "MIN_ACTIVE_KEYS": str(min_active_keys_param.value_as_number),
                "DEACTIVATE_AFTER_DAYS": "60",
            },
        )
        # S3 and KMS permissions
        bucket.grant_read_write(rotate_fn)
        rotate_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kms:CreateKey",
                    "kms:DescribeKey",
                    "kms:TagResource",
                    "kms:Encrypt",
                    "kms:Decrypt",
                ],
                resources=["*"],
            )
        )

        rule = events.Rule(
            self,
            "MonthlyKeyRotationRule",
            schedule=events.Schedule.cron(minute="0", hour="0", day="1", month="*", year="*"),
        )
        rule.add_target(targets.LambdaFunction(rotate_fn))

        # CloudWatch Metrics
        # Lambda metrics
        api_errors_metric = fn.metric_errors(period=Duration.minutes(5))
        rotate_errors_metric = rotate_fn.metric_errors(period=Duration.minutes(60))
        api_invocations = fn.metric_invocations(period=Duration.minutes(5))
        rotate_invocations = rotate_fn.metric_invocations(period=Duration.minutes(60))
        api_duration = fn.metric_duration(period=Duration.minutes(5))

        # API Gateway 5XX
        api_5xx = cw.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5XXError",
            period=Duration.minutes(5),
            statistic="Sum",
            dimensions_map={
                "ApiName": api.rest_api_name,
                "Stage": api.deployment_stage.stage_name,
            },
        )

        # Custom Key Pool metrics
        active_keys_metric = cw.Metric(
            namespace="PQFile/Keys",
            metric_name="ActiveKeysCount",
            period=Duration.minutes(60),
            statistic="Minimum",
        )
        rotation_errors_metric = cw.Metric(
            namespace="PQFile/Keys",
            metric_name="RotationErrors",
            period=Duration.minutes(60),
            statistic="Sum",
        )

        # Alarms
        cw.Alarm(
            self,
            "UnifiedApiLambdaErrorsAlarm",
            metric=api_errors_metric,
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="Unified API Lambda reported errors",
        )

        cw.Alarm(
            self,
            "ApiGateway5xxAlarm",
            metric=api_5xx,
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="API Gateway 5XX errors detected",
        )

        cw.Alarm(
            self,
            "RotateLambdaErrorsAlarm",
            metric=rotate_errors_metric,
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            alarm_description="Key rotation Lambda reported errors",
        )

        cw.Alarm(
            self,
            "ActiveKeysLowAlarm",
            metric=active_keys_metric,
            threshold=min_active_keys_param.value_as_number,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.BREACHING,
            alarm_description="Active key pool below minimum threshold",
        )

        # Dashboard
        dash = cw.Dashboard(self, "PQFileDashboard")
        dash.add_widgets(
            cw.GraphWidget(title="Unified API Lambda - Invocations/Errors", left=[api_invocations], right=[api_errors_metric]),
            cw.GraphWidget(title="Unified API Lambda - Duration", left=[api_duration]),
            cw.GraphWidget(title="API Gateway - 5XX Errors", left=[api_5xx]),
            cw.GraphWidget(title="Rotation Lambda - Invocations/Errors", left=[rotate_invocations], right=[rotate_errors_metric]),
            cw.GraphWidget(title="Key Pool - Active Keys", left=[active_keys_metric]),
        )

        # Outputs
        cdk.CfnOutput(self, "ApiEndpoint", value=api.url, export_name="UnifiedApiUrl")
        cdk.CfnOutput(self, "DocumentsBucketOutput", value=bucket.bucket_name)

