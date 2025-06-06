#!/usr/bin/env python3

import os
import json
import time
import os
import json
import time
import base64
import zipfile
import boto3
import subprocess
import requests
import pg8000.native

# Configuration
LOCALSTACK_ENDPOINT = "http://localhost:4566"
DB_CONFIG = {
    'database': 'pqfile_db',
    'user': 'postgres',
    'password': 'postgres',
    'host': 'localhost',
    'port': 5432,
}
BUCKET_NAME = "documents"
TEST_DOCUMENT = "This is a test document for encryption and decryption. It needs to be exactly 100 characters to test properly." + "A" * 22

# AWS clients
s3_client = boto3.client(
    's3',
    endpoint_url=LOCALSTACK_ENDPOINT,
    aws_access_key_id='test',
    aws_secret_access_key='test',
    region_name='us-east-1'
)

lambda_client = boto3.client(
    'lambda',
    endpoint_url=LOCALSTACK_ENDPOINT,
    aws_access_key_id='test',
    aws_secret_access_key='test',
    region_name='us-east-1'
)

def create_lambda_function(name, handler):
    """Create a Lambda function in LocalStack with DB connection code patched"""
    try:
        # Create a temporary directory for the Lambda package
        temp_dir = f"/tmp/packages/{name}"
        
        # Copy Lambda code files to temp directory
        lambda_dir = f"lambdas/{name}"
        
        # Create zip file directly from the packages directory that already has dependencies
        zip_path = f"/tmp/{name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add all files from the package directory
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)
        
        print(f"Created simplified Lambda package at {zip_path}")
        
        # Read the zip file
        with open(zip_path, 'rb') as f:
            zip_bytes = f.read()
        
        # Create Lambda function
        lambda_client.create_function(
            FunctionName=name,
            Runtime='python3.9',
            Role='arn:aws:iam::000000000000:role/lambda-role',
            Handler=handler,
            Code={'ZipFile': zip_bytes},
            Timeout=30,
            Architectures=['arm64'],
            Environment={
                'Variables': {
                    'DB_HOST': 'postgres',
                    'DB_NAME': 'pqfile_db',
                    'DB_USER': 'postgres',
                    'DB_PASSWORD': 'postgres',
                    'S3_BUCKET': BUCKET_NAME,
                    'S3_ENDPOINT_URL': LOCALSTACK_ENDPOINT,
                    'KMS_ENDPOINT_URL': LOCALSTACK_ENDPOINT,
                    'TEST_MODE': 'true',  # Indicate we're in test mode
                    'AWS_ACCESS_KEY_ID': 'test',
                    'AWS_SECRET_ACCESS_KEY': 'test',
                    'AWS_DEFAULT_REGION': 'us-east-1'
                }
            }
        )
        print(f"Created Lambda function: {name}")
    except Exception as e:
        print(f"Error creating Lambda function {name}: {e}")

def wait_for_services():
    """Wait for Docker containers to be ready"""
    print("Waiting for PostgreSQL to be ready...")
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            # Modified to handle connection retries better
            conn = pg8000.native.Connection(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                database='postgres'
            )
            conn.close()
            print("PostgreSQL is ready!")

            # Now try to connect to the specific database
            try:
                conn = pg8000.native.Connection(**DB_CONFIG)
                conn.close()
                print(f"Database '{DB_CONFIG['database']}' is accessible!")
                break
            except Exception as e:
                if 'does not exist' in str(e):
                    # Create the database if it doesn't exist
                    print(f"Database '{DB_CONFIG['database']}' does not exist. Creating it...")
                    conn = pg8000.native.Connection(
                        host=DB_CONFIG['host'],
                        port=DB_CONFIG['port'],
                        user=DB_CONFIG['user'],
                        password=DB_CONFIG['password'],
                        database='postgres'
                    )
                    conn.run(f"CREATE DATABASE {DB_CONFIG['database']}")
                    conn.close()
                    print(f"Created database '{DB_CONFIG['database']}'")
                    break
                else:
                    raise

        except Exception:
            print(f"Waiting for PostgreSQL... ({attempt+1}/{max_attempts})")
            time.sleep(2)
    
    print("Waiting for LocalStack to be ready...")
    max_attempts = 60  # Increased wait time
    localstack_ready = False
    for attempt in range(max_attempts):
        try:
            # Try a simple request to LocalStack health endpoint
            response = requests.get(f"{LOCALSTACK_ENDPOINT}/_localstack/health", timeout=5)
            if response.status_code == 200:
                services = response.json().get('services', {})
                print(f"LocalStack health response: {services}")
                # Check if necessary services are available (status can be 'running' or 'available')
                s3_status = services.get('s3')
                lambda_status = services.get('lambda')
                kms_status = services.get('kms')
                
                if (s3_status == 'running' or s3_status == 'available') and \
                   (lambda_status == 'running' or lambda_status == 'available') and \
                   (kms_status == 'running' or kms_status == 'available'):
                    print("LocalStack required services are ready!")
                    localstack_ready = True
                    break
                else:
                    print(f"Still waiting for required services. Current status: s3={s3_status}, lambda={lambda_status}, kms={kms_status}")
        except requests.RequestException as e:
            print(f"Request error: {str(e)}")
        except json.JSONDecodeError as e:
            print(f"Invalid JSON response: {str(e)}")
        print(f"Waiting for LocalStack... ({attempt+1}/{max_attempts})")
        time.sleep(2)
    
    if not localstack_ready:
        print("WARNING: LocalStack may not be fully ready, but continuing anyway...")
        return False
    return True

def setup_aws_resources():
    """Set up required AWS resources on LocalStack"""
    # Create S3 bucket if it doesn't exist
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
        print(f"S3 bucket {BUCKET_NAME} already exists")
    except Exception:
        s3_client.create_bucket(Bucket=BUCKET_NAME)
        print(f"Created S3 bucket: {BUCKET_NAME}")

    # Create Lambda functions
    for lambda_name in ['store_lambda', 'retrieve_lambda']:
        handler = "app.lambda_handler"
        try:
            create_lambda_function(lambda_name, handler)
        except Exception as e:
            print(f"Error creating Lambda function {lambda_name} (might already exist): {e}")
    
    # Set up S3 event notification to trigger store_lambda
    try:
        # Add permission for S3 to invoke Lambda
        lambda_client.add_permission(
            FunctionName="store_lambda",
            StatementId="s3-trigger",
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
        )
        
        # Configure bucket notification
        s3_client.put_bucket_notification_configuration(
            Bucket=BUCKET_NAME,
            NotificationConfiguration={
                'LambdaFunctionConfigurations': [
                    {
                        'LambdaFunctionArn': f"arn:aws:lambda:us-east-1:000000000000:function:store_lambda",
                        'Events': ['s3:ObjectCreated:*'],
                        'Filter': {
                            'Key': {
                                'FilterRules': [
                                    {
                                        'Name': 'prefix',
                                        'Value': 'uploads/'
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        )
        print("Set up S3 event notification for store_lambda")
    except Exception as e:
        print(f"Error setting up S3 event notification: {e}")

def wait_for_lambda_ready(function_name, max_attempts=30):
    """Wait until a Lambda function is in the Active state"""
    print(f"Waiting for {function_name} to be ready...")
    for attempt in range(max_attempts):
        try:
            response = lambda_client.get_function(FunctionName=function_name)
            state = response.get('Configuration', {}).get('State')
            if state == 'Active':
                print(f"Function {function_name} is now Active and ready!")
                return True
            print(f"Function {function_name} is in {state} state. Waiting... ({attempt+1}/{max_attempts})")
        except Exception as e:
            print(f"Error checking function state: {str(e)}")
        time.sleep(2)
    print(f"Warning: Timed out waiting for function {function_name} to become Active")
    return False

def create_test_document():
    """Create and upload a test document to trigger the Lambda function"""
    try:
        # Initialize database and create test key if needed
        conn = pg8000.native.Connection(**DB_CONFIG)
        # Check if the tables exist first
        try:
            rows = conn.run("SELECT COUNT(*) FROM encryption_keys")
            key_count = rows[0][0]
            if key_count == 0:
                print("No encryption keys found. The store_lambda will generate one automatically.")
            else:
                print(f"Found {key_count} existing encryption keys")
        except Exception as e:
            if 'does not exist' in str(e) or 'relation' in str(e):
                print("Database tables don't exist yet. Need to initialize schema.")
                print("Running init.sql script...")
                # Read and execute the init.sql file
                with open('init.sql', 'r') as f:
                    sql_init = f.read()
                    # Split by semicolons and execute each statement
                    statements = [stmt.strip() for stmt in sql_init.split(';') if stmt.strip()]
                    for stmt in statements:
                        if stmt:
                            conn.run(stmt)
                    print("Database schema initialized")

                print("Database schema initialized. The store_lambda will generate keys automatically.")
            else:
                raise
        conn.close()
        
        # Upload test document to S3
        test_key = "uploads/test_document.txt"
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=test_key,
            Body=TEST_DOCUMENT.encode('utf-8')
        )
        print(f"Uploaded test document to s3://{BUCKET_NAME}/{test_key}")
        
        # Wait for Lambda functions to be ready
        print("Checking Lambda function readiness...")
        store_ready = wait_for_lambda_ready('store_lambda')
        retrieve_ready = wait_for_lambda_ready('retrieve_lambda')
        
        if not store_ready or not retrieve_ready:
            print("Warning: Lambda functions may not be fully ready, but attempting invocation anyway")
            time.sleep(5)  # Give them a little more time just in case
        
        # In a real environment, the S3 event would trigger the Lambda
        # Since we're testing locally, we'll invoke it directly
        print("Invoking store_lambda directly...")
        store_event = {
            'Records': [
                {
                    's3': {
                        'bucket': {
                            'name': BUCKET_NAME
                        },
                        'object': {
                            'key': test_key
                        }
                    }
                }
            ]
        }
        print(f"Store lambda event: {json.dumps(store_event)}")
        
        try:
            response = lambda_client.invoke(
                FunctionName='store_lambda',
                Payload=json.dumps(store_event),
                LogType='Tail'
            )

            # Log detailed response
            log_result = base64.b64decode(response.get('LogResult', '')).decode('utf-8')
            print(f"Store Lambda logs:\n{log_result}")

            payload = response['Payload'].read().decode('utf-8')
            print(f"Store Lambda response payload:\n{payload}")

            # Check if the response indicates an error
            try:
                response_data = json.loads(payload)
                if 'errorMessage' in response_data:
                    print(f"❌ Lambda function error: {response_data['errorMessage']}")
                    print(f"Error type: {response_data.get('errorType', 'Unknown')}")
                    if 'stackTrace' in response_data:
                        print("Stack trace:")
                        for line in response_data['stackTrace']:
                            print(f"  {line}")

                    # If it's a module import error, let's try a different approach
                    if 'psycopg2' in response_data['errorMessage']:
                        print("\n🔧 Detected psycopg2 import error. This is a common Lambda packaging issue.")
                        print("The Lambda function cannot import the psycopg2 module.")
                        print("This usually happens when:")
                        print("1. The module wasn't properly packaged")
                        print("2. Architecture mismatch (local vs Lambda runtime)")
                        print("3. Missing native dependencies")
                        print("\nTo fix this, you may need to:")
                        print("- Use a Docker container to build the Lambda package")
                        print("- Use AWS Lambda Layers for psycopg2")
                        print("- Use a different PostgreSQL client library")
                        return

            except json.JSONDecodeError:
                print("Could not parse Lambda response as JSON")

            # Get the encrypted key to pass to retrieve_lambda
            encrypted_key = f"{test_key.replace('uploads/', 'encrypted/')}"
            print(f"Encrypted document should be at: s3://{BUCKET_NAME}/{encrypted_key}")

            # Check if encrypted file exists
            try:
                s3_client.head_object(Bucket=BUCKET_NAME, Key=encrypted_key)
                print(f"✅ Verified encrypted file exists")
            except Exception as e:
                print(f"❌ Error: Encrypted file not found: {str(e)}")
                # List contents of the bucket to see what's there
                print("Listing bucket contents:")
                objects = s3_client.list_objects_v2(Bucket=BUCKET_NAME)
                for obj in objects.get('Contents', []):
                    print(f"  - {obj['Key']}")
        except Exception as e:
            print(f"Error invoking store_lambda: {str(e)}")
            return
        response_body = json.loads(payload).get('body', '{}')
        print("Encryption response:")
        print(response_body)

        # Parse the response to get the encrypted file location
        processed_results = json.loads(response_body).get('processed', [])
        if not processed_results or 'encrypted' not in processed_results[0]:
            print("❌ Error: No encrypted file location found in response")
            return

        encrypted_s3_path = processed_results[0]['encrypted']
        encrypted_key = encrypted_s3_path.replace('s3://documents/', '')

        # Download the encrypted package from S3
        print(f"\nDownloading encrypted package from {encrypted_s3_path}...")
        try:
            response = s3_client.get_object(Bucket=BUCKET_NAME, Key=encrypted_key)
            encrypted_package = json.loads(response['Body'].read().decode('utf-8'))
            print("Successfully downloaded encrypted package")
        except Exception as e:
            print(f"❌ Error downloading encrypted package: {e}")
            return

        # Now test decryption
        print("\nTesting decryption...")
        response = lambda_client.invoke(
            FunctionName='retrieve_lambda',
            Payload=json.dumps({
                'body': {
                    'encrypted_package': encrypted_package,
                    'output_format': 'text'
                }
            })
        )
        
        payload = json.loads(response['Payload'].read().decode('utf-8'))
        decrypted_result = json.loads(payload.get('body', '{}'))
        
        if decrypted_result.get('is_base64_encoded', False):
            decrypted_text = base64.b64decode(decrypted_result.get('document_content', '')).decode('utf-8')
        else:
            decrypted_text = decrypted_result.get('document_content', '')
        
        print(f"Decrypted result: {decrypted_text}")
        
        # Verify if decryption was successful
        if decrypted_text == TEST_DOCUMENT:
            print("\n✅ SUCCESS: Document was correctly encrypted and decrypted!")
        else:
            print("\n❌ FAILURE: Decrypted content doesn't match original document")
            
    except Exception as e:
        print(f"Error during test: {e}")

if __name__ == "__main__":
    # Start Docker containers if they're not already running
    print("Checking if Docker containers are running...")
    result = subprocess.run(
        ["docker-compose", "ps", "-q"], 
        capture_output=True,
        text=True
    )
    
    if not result.stdout.strip():
        print("Starting Docker containers...")
        subprocess.run(["docker-compose", "up", "-d"])
        print("Docker containers started. Waiting for services to be ready...")
    else:
        print("Docker containers are already running")
    
    # Wait for services to be ready
    wait_for_services()
    
    # Set up AWS resources
    print("\nSetting up AWS resources...")
    setup_aws_resources()
    
    # Create and test with a document
    print("\nCreating test document...")
    create_test_document()
    
    print("\nTest completed.")
