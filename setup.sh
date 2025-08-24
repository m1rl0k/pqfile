#!/bin/bash

# Check for Python
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
    PIP_CMD=pip3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
    PIP_CMD=pip
else
    echo "Error: Python is not installed. Please install Python 3." >&2
    exit 1
fi

# Check for pip
if ! command -v $PIP_CMD &>/dev/null; then
    echo "Error: pip is not installed. Please install pip." >&2
    exit 1
fi

# Install dependencies
echo "Installing Python dependencies using $PIP_CMD..."
$PIP_CMD install boto3 pg8000 cryptography requests pqcrypto

# Set up environment
echo "Starting Docker environment..."
docker-compose down # Ensure clean start
docker-compose up -d

# Wait for services to be available
echo "Waiting for services to be available..."
sleep 15

# Update the test_local.py script to use the correct LocalStack port
echo "Updating test script with correct LocalStack port..."
sed -i '' 's/LOCALSTACK_ENDPOINT = "http:\/\/localhost:4567"/LOCALSTACK_ENDPOINT = "http:\/\/localhost:4566"/' test_local.py

# Create the Lambda deployment packages
echo "Creating Lambda deployment packages..."
mkdir -p /tmp/packages

# Function to create Lambda package with proper dependencies
create_lambda_package() {
    local lambda_name=$1
    local package_dir="/tmp/packages/$lambda_name"

    echo "Creating package for $lambda_name..."

    # Clean and create package directory
    rm -rf "$package_dir"
    mkdir -p "$package_dir"

    # Copy Lambda source files
    cp -r "./lambdas/$lambda_name/"* "$package_dir/"

    # Install dependencies with specific options for Lambda compatibility
    cd "$package_dir"

    # Use Docker to build packages with correct Linux ARM64 architecture
    echo "Building dependencies for $lambda_name using Docker..."

    # Create a simple container to build and extract packages
    docker run --rm \
        -v "$(pwd)/requirements.txt:/tmp/requirements.txt:ro" \
        -v "$(pwd):/output" \
        --platform linux/arm64 \
        python:3.9-slim \
        sh -c "pip install -r /tmp/requirements.txt -t /tmp/packages && cp -r /tmp/packages/* /output/"

    # Verify pg8000 installation
    if [ -d "pg8000" ] || ls pg8000* 1> /dev/null 2>&1; then
        echo "✅ pg8000 successfully installed for $lambda_name"
    else
        echo "❌ Warning: pg8000 not found in package for $lambda_name"
        echo "Contents of package directory:"
        ls -la
    fi

    cd - > /dev/null
}

# Create packages for both Lambda functions
create_lambda_package "store_lambda"
create_lambda_package "retrieve_lambda"

# Verify package contents
echo "Verifying Lambda packages..."
for lambda_name in "store_lambda" "retrieve_lambda"; do
    package_dir="/tmp/packages/$lambda_name"
    echo "Contents of $lambda_name package:"
    ls -la "$package_dir" | head -20
    echo "Checking for pg8000..."
    find "$package_dir" -name "*pg8000*" -type d | head -5
    find "$package_dir" -name "*pg8000*" -type f | head -5
    echo "---"
done

echo "Environment is set up. Running test script..."
$PYTHON_CMD test_local.py
