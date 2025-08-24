#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.unified_api_stack import UnifiedApiStack


app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
)

UnifiedApiStack(
    app,
    "PQFile-UnifiedApi",
    env=env,
)

app.synth()

