#!/bin/bash

# PQFile Deployment Script
# Deploys the unified API architecture with isolated database backup

set -e

# Configuration
ENVIRONMENT=${1:-dev}
AWS_REGION=${AWS_REGION:-us-east-1}
STACK_NAME="pqfile-${ENVIRONMENT}"

echo "🚀 Deploying PQFile ${ENVIRONMENT} environment..."

# Check if AWS CLI is configured
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "❌ AWS CLI not configured. Please run 'aws configure' first."
    exit 1
fi

# Build Lambda package
echo "📦 Building Lambda deployment package..."
cd lambdas/unified_api

# Create deployment package
rm -rf package/
mkdir -p package/

# Install dependencies
pip install -r requirements.txt -t package/

# Copy Lambda code
cp app.py package/

# Create ZIP file
cd package/
zip -r ../deployment-package.zip .
cd ..

echo "✅ Lambda package built: lambdas/unified_api/deployment-package.zip"

# Go back to root
cd ../../

# Get database configuration
echo "🔧 Database configuration required..."
read -p "Enter PostgreSQL host (isolated VPC): " DB_HOST
read -s -p "Enter PostgreSQL password: " DB_PASSWORD
echo

# Deploy CloudFormation stack
echo "☁️ Deploying CloudFormation stack..."

aws cloudformation deploy \
    --template-file cloudformation/api-gateway-template.yaml \
    --stack-name ${STACK_NAME} \
    --parameter-overrides \
        Environment=${ENVIRONMENT} \
        DatabaseHost=${DB_HOST} \
        DatabasePassword=${DB_PASSWORD} \
    --capabilities CAPABILITY_IAM \
    --region ${AWS_REGION}

# Update Lambda function code
echo "🔄 Updating Lambda function code..."
FUNCTION_NAME="pqfile-api-${ENVIRONMENT}"

aws lambda update-function-code \
    --function-name ${FUNCTION_NAME} \
    --zip-file fileb://lambdas/unified_api/deployment-package.zip \
    --region ${AWS_REGION}

# Get API endpoint
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name ${STACK_NAME} \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text \
    --region ${AWS_REGION})

echo "✅ Deployment complete!"
echo ""
echo "📋 Deployment Summary:"
echo "   Environment: ${ENVIRONMENT}"
echo "   API Endpoint: ${API_ENDPOINT}"
echo "   Stack Name: ${STACK_NAME}"
echo ""
echo "🔗 API Endpoints:"
echo "   POST ${API_ENDPOINT}/encrypt"
echo "   GET  ${API_ENDPOINT}/decrypt/{document_id}"
echo "   POST ${API_ENDPOINT}/admin/rotate-keys"
echo ""
echo "🧪 Test your API:"
echo "   curl -X POST ${API_ENDPOINT}/encrypt \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"content\": \"Hello, World!\"}'"
echo ""
echo "🔐 Your isolated database at ${DB_HOST} serves as the critical backup key store."
echo "   This is your 'oh shit button' for key recovery if KMS keys are lost."
