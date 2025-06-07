import os
import json
import uuid
import datetime
import boto3
import pg8000.native
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# Real post-quantum cryptography implementation using ML-KEM-768 (Kyber768) + AES
import pqcrypto.kem.ml_kem_768

# Configuration
DB_CONFIG = {
    'dbname': os.environ.get('DB_NAME', 'pqfile_db'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'postgres'),
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': os.environ.get('DB_PORT', '5432'),
}

# Database connection function for pg8000
def get_db_connection():
    """Get a database connection using pg8000"""
    return pg8000.native.Connection(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        database=DB_CONFIG['dbname'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password']
    )

# Initialize AWS clients
if os.environ.get('TEST_MODE') == 'true':
    # Running in LocalStack - use internal container endpoint
    kms_client = boto3.client(
        'kms',
        endpoint_url='http://localstack:4566',
        aws_access_key_id='test',
        aws_secret_access_key='test',
        region_name='us-east-1'
    )
else:
    # Running in real AWS - use IAM role
    kms_client = boto3.client('kms', region_name='us-east-1')

# Real ML-KEM-768 constants from the library
KYBER_PUBLIC_KEY_SIZE = pqcrypto.kem.ml_kem_768.PUBLIC_KEY_SIZE
KYBER_PRIVATE_KEY_SIZE = pqcrypto.kem.ml_kem_768.SECRET_KEY_SIZE
KYBER_CIPHERTEXT_SIZE = pqcrypto.kem.ml_kem_768.CIPHERTEXT_SIZE
KYBER_SHARED_SECRET_SIZE = 32

def get_active_key():
    """Get an active encryption key from the pool"""
    conn = get_db_connection()
    try:
        # Find a key that's active and has been used the least
        rows = conn.run("""
            SELECT id, public_key, private_key, kms_key_id, kms_key_arn
            FROM encryption_keys
            WHERE status = 'active'
            ORDER BY usage_count ASC
            LIMIT 1
        """)

        if not rows:
            # If no active key exists, create a new one
            return create_new_key(conn)

        key = dict(zip(['id', 'public_key', 'private_key', 'kms_key_id', 'kms_key_arn'], rows[0]))

        # Increment usage count
        conn.run("""
            UPDATE encryption_keys
            SET usage_count = usage_count + 1
            WHERE id = :key_id
        """, key_id=key['id'])

        return key
    finally:
        conn.close()

def log_operation(operation_type, document_id=None, key_id=None):
    """Log operations for audit and tracking purposes"""
    conn = get_db_connection()
    try:
        conn.run("""
            INSERT INTO access_logs (document_id, access_type)
            VALUES (:document_id, :access_type)
        """, document_id=document_id or 'unknown', access_type=operation_type)
    except Exception as e:
        print(f"Warning: Failed to log operation {operation_type}: {e}")
    finally:
        conn.close()

def create_new_key(conn=None):
    """Create a new ML-KEM-768 (Kyber768) encryption key pair for post-quantum security"""
    # Generate a real ML-KEM-768 key pair
    public_key, private_key = pqcrypto.kem.ml_kem_768.generate_keypair()
    
    # Encode keys to base64 for storage
    public_key_b64 = base64.b64encode(public_key).decode('utf-8')
    private_key_b64 = base64.b64encode(private_key).decode('utf-8')
    
    # Create KMS key for the public key
    kms_response = kms_client.create_key(
        Description=f'PQFile Kyber Public Key - {datetime.datetime.now().isoformat()}',
        KeyUsage='ENCRYPT_DECRYPT',
        Origin='AWS_KMS',
        Tags=[
            {
                'TagKey': 'Purpose',
                'TagValue': 'PQCrypto'
            },
        ]
    )
    
    kms_key_id = kms_response['KeyMetadata']['KeyId']
    kms_key_arn = kms_response['KeyMetadata']['Arn']
    
    # Store the public key in KMS as well (simulating import, which isn't actually 
    # possible directly for asymmetric keys in KMS - in a real implementation 
    # you might use a different approach)
    kms_client.tag_resource(
        KeyId=kms_key_id,
        Tags=[
            {
                'TagKey': 'PublicKeyHash',
                'TagValue': hashlib.sha256(public_key).hexdigest()
            }
        ]
    )
    
    # Store in database
    if not conn:
        conn = get_db_connection()
        close_conn = True
    else:
        close_conn = False

    try:
        rows = conn.run("""
            INSERT INTO encryption_keys
            (public_key, private_key, kms_key_id, kms_key_arn)
            VALUES (:public_key, :private_key, :kms_key_id, :kms_key_arn)
            RETURNING id, public_key, private_key, kms_key_id, kms_key_arn
        """, public_key=public_key_b64, private_key=private_key_b64,
             kms_key_id=kms_key_id, kms_key_arn=kms_key_arn)

        if rows:
            return dict(zip(['id', 'public_key', 'private_key', 'kms_key_id', 'kms_key_arn'], rows[0]))
        return None
    finally:
        if close_conn:
            conn.close()

def check_for_keys_to_rotate():
    """Check for keys that need to be rotated (older than 30 days)"""
    conn = get_db_connection()
    try:
        # Use the function we created in the schema
        rows = conn.run("SELECT * FROM find_keys_for_rotation() LIMIT 10")

        for row in rows:
            key_id = row[0]  # Assuming first column is key_id

            # Create a new key for rotation
            new_key = create_new_key(conn)

            # Queue the key for rotation
            conn.run("""
                INSERT INTO key_rotations (old_key_id, new_key_id, status)
                VALUES (:old_key_id, :new_key_id, 'pending')
            """, old_key_id=key_id, new_key_id=new_key['id'])

            # Update the old key status
            conn.run("""
                UPDATE encryption_keys
                SET status = 'rotation_queued'
                WHERE id = :key_id
            """, key_id=key_id)

        return {
            'keys_queued_for_rotation': len(rows)
        }
    finally:
        conn.close()


def encrypt_document(document_data, key=None, document_id=None):
    """Encrypt a document with post-quantum cryptography"""
    if key is None:
        key = get_active_key()

    # Load public key from base64
    public_key = base64.b64decode(key['public_key'])

    # Use ML-KEM-768 to encapsulate a shared secret
    ciphertext, shared_secret = pqcrypto.kem.ml_kem_768.encrypt(public_key)

    # Convert shared secret to an AES key
    aes_key = hashlib.sha256(shared_secret).digest()

    # Use AES to encrypt the actual document data
    iv = os.urandom(16)  # AES block size
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(document_data) + padder.finalize()

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    # Format includes key ID, ciphertext (for shared secret recovery), IV, and encrypted data
    result = {
        'key_id': key['id'],
        'ciphertext': base64.b64encode(ciphertext).decode('utf-8'),
        'iv': base64.b64encode(iv).decode('utf-8'),
        'encrypted_data': base64.b64encode(encrypted_data).decode('utf-8'),
        'metadata': {
            'encryption_algorithm': 'ML-KEM-768-AES256-CBC',
            'created_at': datetime.datetime.now().isoformat(),
            'kms_key_id': key['kms_key_id'],
            'document_id': document_id
        }
    }
    
    return result

def lambda_handler(event, context):
    """AWS Lambda entry point"""
    try:
        # Maintenance operations
        if event.get('operation') == 'check_for_keys_to_rotate':
            result = check_for_keys_to_rotate()
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }

        # Handle S3 events
        if 'Records' in event:
            # Configure S3 client for LocalStack
            if os.environ.get('TEST_MODE') == 'true':
                # Running in LocalStack - use LocalStack internal endpoint and credentials
                s3_client = boto3.client(
                    's3',
                    endpoint_url='http://localstack:4566',  # Use internal container name
                    aws_access_key_id='test',
                    aws_secret_access_key='test',
                    region_name='us-east-1'
                )
            else:
                # Running in real AWS - use IAM role
                s3_client = boto3.client('s3', region_name='us-east-1')

            results = []

            for record in event['Records']:
                # Extract S3 bucket and key from the event
                bucket_name = record['s3']['bucket']['name']
                object_key = record['s3']['object']['key']

                print(f"Processing S3 object: s3://{bucket_name}/{object_key}")

                # Download the document from S3
                try:
                    response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
                    document_data = response['Body'].read()

                    # Ensure document size is within limits
                    max_size_bytes = int(os.environ.get('MAX_DOCUMENT_SIZE_BYTES', 20 * 1024 * 1024))
                    if len(document_data) > max_size_bytes:
                        print(f"Document size {len(document_data)} exceeds maximum allowed size of {max_size_bytes} bytes")
                        continue

                    # Encrypt the document
                    encrypted_result = encrypt_document(document_data, document_id=object_key)

                    # Store encrypted document back to S3 in encrypted/ prefix
                    encrypted_key = object_key.replace('uploads/', 'encrypted/')
                    # Store with S3 server-side encryption (SSE-KMS) as a second layer
                    s3_client.put_object(
                        Bucket=bucket_name,
                        Key=encrypted_key,
                        Body=json.dumps(encrypted_result),
                        ContentType='application/json',
                        ServerSideEncryption='aws:kms',
                        # Use the same KMS key that was used for primary encryption 
                        SSEKMSKeyId=encrypted_result['metadata']['kms_key_id']
                    )

                    # Log the encryption operation
                    log_operation('encrypt', document_id=object_key, key_id=encrypted_result['key_id'])

                    print(f"Successfully encrypted and stored: s3://{bucket_name}/{encrypted_key}")
                    results.append({
                        'source': f"s3://{bucket_name}/{object_key}",
                        'encrypted': f"s3://{bucket_name}/{encrypted_key}",
                        'key_id': encrypted_result['key_id']
                    })

                except Exception as e:
                    print(f"Error processing {object_key}: {str(e)}")
                    results.append({
                        'source': f"s3://{bucket_name}/{object_key}",
                        'error': str(e)
                    })

            return {
                'statusCode': 200,
                'body': json.dumps({'processed': results})
            }

        # Handle direct API calls (for testing)
        if 'body' not in event:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing document data'})
            }

        # Parse the body content
        body = event['body']
        if isinstance(body, str):
            body = json.loads(body)

        document_content = body.get('content')
        if not document_content:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing document content'})
            }

        # Handle base64 encoded content
        if body.get('isBase64Encoded', False):
            document_data = base64.b64decode(document_content)
        else:
            document_data = document_content.encode('utf-8')

        # Ensure document size is within limits
        max_size_bytes = int(os.environ.get('MAX_DOCUMENT_SIZE_BYTES', 20 * 1024 * 1024))
        if len(document_data) > max_size_bytes:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': f'Document size exceeds maximum allowed size of {max_size_bytes} bytes'
                })
            }

        # Encrypt the document
        encrypted_result = encrypt_document(document_data)

        return {
            'statusCode': 200,
            'body': json.dumps(encrypted_result)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

# For local testing
if __name__ == '__main__':
    # Create test document
    test_data = "This is a test document for encryption."
    result = encrypt_document(test_data.encode('utf-8'))
    print(json.dumps(result, indent=2))
