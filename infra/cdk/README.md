# PQFile CDK (Python) - Unified API

This CDK app deploys:
- A single Lambda function (lambdas/unified_api/app.py)
- An API Gateway REST API with routes:
  - POST /encrypt
  - GET /decrypt/{document_id}
- An S3 bucket for encrypted documents
- IAM permissions for S3 access and KMS usage/creation

## Prerequisites
- Python 3.11 or 3.12
- AWS CDK v2 installed (`npm install -g aws-cdk`)
- AWS credentials configured (e.g., `aws configure`)

## Install dependencies
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r infra/cdk/requirements.txt
```

## Bootstrap (first time per account/region)
```
cd infra/cdk
cdk bootstrap
```

## Deploy
```
cd infra/cdk
cdk deploy \
  -c DB_HOST=<db-host> \
  -c DB_NAME=pqfile_db \
  -c DB_USER=postgres \
  -c DB_PASSWORD=postgres \
  -c DocumentsBucketName=documents
```

Alternatively, pass parameters interactively during `cdk deploy`.

## Notes
- The Lambda code is packaged directly from `lambdas/unified_api`. If you need to vendor dependencies, consider CDK Bundling/Docker or Lambda Layers.
- For production, consider scoping KMS IAM permissions to managed keys/aliases relevant to your rotation strategy.

