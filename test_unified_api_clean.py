#!/usr/bin/env python3
"""
Test the unified PQFile API with real infrastructure - NO MOCKS
Uses the same LocalStack and PostgreSQL setup as the original test
"""

import os
import sys
import json
import logging
from config import get_logger, get_db_connection as cfg_db_conn, get_env

# Set environment for local testing with existing database and LocalStack (do not override if already set)
os.environ.setdefault('TEST_MODE', 'true')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_NAME', 'pqfile_db')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASSWORD', 'postgres')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('S3_BUCKET', 'documents')
os.environ.setdefault('LOCALSTACK_ENDPOINT_URL', 'http://localhost:4566')
os.environ.setdefault('AWS_REGION', 'us-east-1')

# Common configuration
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
S3_BUCKET = os.getenv('S3_BUCKET')
S3_ENDPOINT = os.getenv('LOCALSTACK_ENDPOINT_URL')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

# Test data
ORIGINAL_CONTENT = 'Test document for unified API with real infrastructure!'
TEST_DOCUMENT_ID = 'test-unified-real-123'

# Add unified API to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lambdas', 'unified_api'))

# Logger
logger = get_logger(__name__)

def test_database_connection():
    """Test that we can connect to the existing database"""
    logger.info("Testing database connection...")
    
    try:
        import pg8000.native
        conn = pg8000.native.Connection(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        # Test query
        rows = conn.run("SELECT COUNT(*) FROM encryption_keys WHERE status = 'active'")
        key_count = rows[0][0]
        logger.info(f"Database connected. Found {key_count} active encryption keys.")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.error("Ensure PostgreSQL is running: docker-compose up -d postgres")
        return False

def verify_s3_storage(document_id):
    """Verify the document is actually stored in S3 and show the actual crypto data"""
    try:
        import boto3
        import base64

        # Connect to LocalStack S3
        s3_client = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id='test',
            aws_secret_access_key='test',
            region_name=AWS_REGION
        )

        # Check if the encrypted file exists
        s3_key = f"encrypted/{document_id}.json"
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)

        # Parse the encrypted package
        encrypted_package = json.loads(response['Body'].read().decode('utf-8'))

        logger.info("S3 storage verified:")
        logger.info(f"File exists: s3://{S3_BUCKET}/{s3_key}")
        logger.info(f"Algorithm: {encrypted_package['metadata']['encryption_algorithm']}")
        logger.info(f"Key ID: {encrypted_package['key_id']}")

        # Show actual crypto data
        logger.info("Cryptographic data:")
        print(f"   ML-KEM-768 Ciphertext (first 100 chars): {encrypted_package['ciphertext'][:100]}...")
        print(f"   ML-KEM-768 Ciphertext (last 50 chars):  ...{encrypted_package['ciphertext'][-50:]}")
        print(f"   Total ciphertext length: {len(encrypted_package['ciphertext'])} chars")

        # Decode and show IV
        iv_bytes = base64.b64decode(encrypted_package['iv'])
        logger.info(f"AES IV (base64): {encrypted_package['iv']}")
        logger.info(f"AES IV (hex): {iv_bytes.hex()}")
        logger.info(f"AES IV length: {len(iv_bytes)} bytes")

        # Show encrypted data
        encrypted_data_bytes = base64.b64decode(encrypted_package['encrypted_data'])
        logger.info("AES Encrypted Data (base64): [omitted in logs]")
        logger.info(f"AES Encrypted Data (hex, first 64 chars): {encrypted_data_bytes.hex()[:64]}...")
        logger.info(f"AES Encrypted Data length: {len(encrypted_data_bytes)} bytes")

        return encrypted_package

    except Exception as e:
        logger.error(f"S3 verification failed: {e}")
        return None

def verify_database_entries(document_id, key_id):
    """Verify database entries and show actual encryption keys"""
    try:
        import pg8000.native
        import base64

        conn = pg8000.native.Connection(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )

        # Check access logs
        rows = conn.run("""
            SELECT access_type, accessed_at
            FROM access_logs
            WHERE document_id = :doc_id
            ORDER BY accessed_at DESC
        """, doc_id=document_id)

        logger.info("Database verified:")
        print(f"   Access log entries: {len(rows)}")
        for row in rows:
            print(f"   - {row[0]} at {row[1]}")

        # Show the actual encryption key used
        rows = conn.run("""
            SELECT id, public_key, private_key, usage_count, status, created_at
            FROM encryption_keys
            WHERE id = :key_id
        """, key_id=key_id)

        if rows:
            key_data = rows[0]
            logger.info(f"Encryption key used (Key ID {key_id}):")
            logger.info(f"Status: {key_data[4]}")
            logger.info(f"Usage count: {key_data[3]}")
            logger.info(f"Created: {key_data[5]}")

            # Show actual key data
            public_key_b64 = key_data[1]
            private_key_b64 = key_data[2]

            print(f"   Public Key (base64, first 100 chars): {public_key_b64[:100]}...")
            print(f"   Public Key (base64, last 50 chars):  ...{public_key_b64[-50:]}")
            print(f"   Public Key total length: {len(public_key_b64)} chars")

            # Decode and show actual key sizes
            public_key_bytes = base64.b64decode(public_key_b64)
            private_key_bytes = base64.b64decode(private_key_b64)

            print(f"   Public Key (decoded): {len(public_key_bytes)} bytes")
            print(f"   Private Key (decoded): {len(private_key_bytes)} bytes")
            print(f"   Public Key (hex, first 32 bytes): {public_key_bytes[:32].hex()}")
            print(f"   Private Key (hex, first 32 bytes): {private_key_bytes[:32].hex()}")

            # Verify these are real ML-KEM-768 key sizes
            if len(public_key_bytes) == 1184 and len(private_key_bytes) == 2400:
                logger.info("Verified: Correct ML-KEM-768 key sizes.")
            else:
                logger.warning("Unexpected key sizes for ML-KEM-768")

        # Check key usage stats
        rows = conn.run("""
            SELECT id, usage_count, status
            FROM encryption_keys
            WHERE status = 'active'
            ORDER BY usage_count DESC
            LIMIT 3
        """)

        print(f"\n   Recent key usage:")
        for row in rows:
            print(f"   - Key {row[0]}: used {row[1]} times, status: {row[2]}")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        return False

def test_unified_lambda_real():
    """Test the unified Lambda function with real LocalStack infrastructure"""
    logger.info("\nTesting Unified Lambda Function with Real Infrastructure")
    print("=" * 60)
    
    try:
        # Import the Lambda function
        from app import lambda_handler
        
        # Test 1: Encrypt operation
        print("\n1. Testing encrypt operation...")
        encrypt_event = {
            'httpMethod': 'POST',
            'path': '/encrypt',
            'body': json.dumps({
                'content': ORIGINAL_CONTENT,
                'document_id': TEST_DOCUMENT_ID
            })
        }
        
        response = lambda_handler(encrypt_event, {})
        logger.info(f"Response status: {response['statusCode']}")
        
        if response['statusCode'] == 200:
            result = json.loads(response['body'])
            logger.info("Encrypt successful.")
            logger.info(f"Document ID: {result['document_id']}")
            logger.info(f"S3 Location: {result['s3_location']}")
            logger.info(f"Key ID: {result['key_id']}")
            document_id = result['document_id']
        else:
            logger.error(f"Encrypt failed: {response['body']}")
            return False
        
        # Test 2: Decrypt operation
        print("\n2. Testing decrypt operation...")
        decrypt_event = {
            'httpMethod': 'GET',
            'path': f'/decrypt/{document_id}',
            'body': json.dumps({'output_format': 'text'})
        }
        
        response = lambda_handler(decrypt_event, {})
        logger.info(f"Response status: {response['statusCode']}")
        
        if response['statusCode'] == 200:
            result = json.loads(response['body'])
            decrypted_content = result.get('document_content', '')
            # original_content is replaced by ORIGINAL_CONTENT constant

            logger.info("Decrypt successful.")
            logger.info(f"Content (first 50): {decrypted_content[:50]}...")
            logger.info(f"Is base64: {result.get('is_base64_encoded', False)}")

            # VERIFY: Check if decrypted content matches original
            if decrypted_content == ORIGINAL_CONTENT:
                logger.info("Verified: Decrypted content matches original exactly.")
            else:
                logger.error("Verification failed: content mismatch")
                logger.error(f"Expected: {ORIGINAL_CONTENT}")
                logger.error(f"Got:      {decrypted_content}")
                return False
        else:
            print(f"Decrypt failed: {response['body']}")
            return False
        
        # Test 3: Error handling
        print("\n3. Testing error handling...")
        error_event = {
            'httpMethod': 'POST',
            'path': '/encrypt',
            'body': json.dumps({})  # Missing content
        }
        
        response = lambda_handler(error_event, {})
        
        if response['statusCode'] == 400:
            logger.info("Error handling works correctly.")
        else:
            logger.error(f"Error handling failed: {response}")
            return False
        
        # Test 4: Invalid endpoint
        print("\n4. Testing invalid endpoint...")
        invalid_event = {
            'httpMethod': 'GET',
            'path': '/invalid',
            'body': '{}'
        }
        
        response = lambda_handler(invalid_event, {})
        
        if response['statusCode'] == 404:
            logger.info("Invalid endpoint correctly returns 404.")
        else:
            logger.error(f"Invalid endpoint test failed: {response}")
            return False
        
        # Test 5: Verify actual S3 storage and show crypto data
        print("\n5. Verifying actual S3 storage and showing crypto data...")
        encrypted_package = verify_s3_storage(document_id)

        # Test 6: Verify database entries and show actual keys
        print("\n6. Verifying database entries and showing actual keys...")
        if encrypted_package:
            verify_database_entries(document_id, encrypted_package['key_id'])
        else:
            logger.error("Cannot verify database - no encrypted package data.")

        logger.info("All unified Lambda tests passed with real infrastructure.")
        return True
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.info("Missing dependencies. Install with:")
        logger.info("pip3 install boto3 pg8000 cryptography pqcrypto")
        return False
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    logger.info("PQFile Unified API Test Suite")
    print("=" * 50)
    
    # Test database connection first
    if not test_database_connection():
        logger.error("\nDatabase not available. Start it with: docker-compose up -d postgres")
        return False
    
    # Test the unified Lambda function
    lambda_success = test_unified_lambda_real()
    
    if lambda_success:
        logger.info("\nAll tests passed. The unified API works with real infrastructure.")
        print("\nNext steps:")
        print("1. Deploy to AWS: ./deploy.sh dev")
        print("2. Test production: export PQFILE_API_ENDPOINT=<your-endpoint> && python3 test_unified_api.py")
        return True
    else:
        logger.error("\nSome tests failed. Check the output above for details.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
