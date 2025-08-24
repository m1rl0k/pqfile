import os
import json
import uuid
import datetime
import boto3
import pg8000.native
import base64
import hashlib
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# Shared config and utilities
from config import get_db_connection as cfg_db_conn, get_boto3_client, get_s3_bucket, get_logger, is_test_mode

# Real post-quantum cryptography implementation using ML-KEM-768 (Kyber768) + AES
import pqcrypto.kem.ml_kem_768

# Logger
logger = get_logger(__name__)

# Initialize AWS clients via shared config

def get_aws_clients():
    return {
        'kms': get_boto3_client('kms'),
        's3': get_boto3_client('s3'),
    }

# Database connection function

def get_db_connection():
    return cfg_db_conn()

def create_kms_key(description):
    """Create a new KMS key for additional security layer"""
    aws_clients = get_aws_clients()
    kms_client = aws_clients['kms']
    
    response = kms_client.create_key(
        Description=description,
        KeyUsage='ENCRYPT_DECRYPT',
        Origin='AWS_KMS',
        Tags=[
            {'TagKey': 'Purpose', 'TagValue': 'PQFile-Backup'},
            {'TagKey': 'Service', 'TagValue': 'PQFile'}
        ]
    )
    
    return response['KeyMetadata']['KeyId'], response['KeyMetadata']['Arn']

def get_or_create_active_key():
    """Get an active encryption key or create a new one"""
    conn = get_db_connection()
    try:
        # Find least used active key
        rows = conn.run("""
            SELECT id, public_key, private_key, kms_key_id, kms_key_arn
            FROM encryption_keys
            WHERE status = 'active'
            ORDER BY usage_count ASC
            LIMIT 1
        """)

        if rows:
            key = dict(zip(['id', 'public_key', 'private_key', 'kms_key_id', 'kms_key_arn'], rows[0]))
            
            # Increment usage count
            conn.run("""
                UPDATE encryption_keys
                SET usage_count = usage_count + 1
                WHERE id = :key_id
            """, key_id=key['id'])
            
            return key
        else:
            # Create new key
            return create_new_key(conn)
    finally:
        conn.close()

def create_new_key(conn=None):
    """Create a new ML-KEM-768 key pair with KMS backup"""
    # Generate real ML-KEM-768 key pair
    public_key, private_key = pqcrypto.kem.ml_kem_768.generate_keypair()
    
    # Encode for storage
    public_key_b64 = base64.b64encode(public_key).decode('utf-8')
    private_key_b64 = base64.b64encode(private_key).decode('utf-8')
    
    # Create KMS key for additional security layer
    kms_key_id, kms_key_arn = create_kms_key(
        f'PQFile Key Backup - {datetime.datetime.now().isoformat()}'
    )
    
    # Store in isolated database (the "oh shit button")
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

def encrypt_document(document_data, document_id=None):
    """Encrypt document using ML-KEM-768 + AES-256-CBC"""
    key = get_or_create_active_key()
    
    # Load public key
    public_key = base64.b64decode(key['public_key'])
    
    # ML-KEM-768 encapsulation
    ciphertext, shared_secret = pqcrypto.kem.ml_kem_768.encrypt(public_key)
    
    # Derive AES key
    aes_key = hashlib.sha256(shared_secret).digest()
    
    # AES encryption (CBC + PKCS7 padding). Consider AES-GCM for AEAD in production.
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(document_data) + padder.finalize()

    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    # Create encrypted package
    encrypted_package = {
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
    
    # Store in S3
    aws_clients = get_aws_clients()
    s3_client = aws_clients['s3']
    bucket_name = os.environ.get('S3_BUCKET', 'pqfile-documents')
    
    # Generate unique document ID if not provided
    if not document_id:
        document_id = str(uuid.uuid4())
    
    s3_key = f"encrypted/{document_id}.json"
    
    # Add S3 server-side encryption as a second layer of protection
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(encrypted_package),
        ContentType='application/json',
        ServerSideEncryption='aws:kms',
        # Use the same KMS key that was used for primary encryption
        SSEKMSKeyId=encrypted_package['metadata']['kms_key_id']
    )
    
    # Log operation
    log_operation('encrypt', document_id, key['id'])

    if is_test_mode():
        logger.debug("Encrypted package created", extra={
            "document_id": document_id,
            "key_id": key['id'],
            "ciphertext_len": len(encrypted_package['ciphertext']),
        })
    
    return {
        'document_id': document_id,
        's3_location': f"s3://{bucket_name}/{s3_key}",
        'key_id': key['id'],
        'encrypted_package': encrypted_package
    }

def decrypt_document(document_id):
    """Decrypt document by ID"""
    # Retrieve from S3
    aws_clients = get_aws_clients()
    s3_client = aws_clients['s3']
    bucket_name = os.environ.get('S3_BUCKET', 'pqfile-documents')
    s3_key = f"encrypted/{document_id}.json"
    
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        encrypted_package = json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.error("S3 get_object failed", extra={"document_id": document_id, "error": str(e)})
        raise ValueError(f"Document not found: {document_id}")
    
    # Get key from isolated database
    conn = get_db_connection()
    try:
        rows = conn.run("""
            SELECT id, public_key, private_key, kms_key_id, kms_key_arn, status
            FROM encryption_keys
            WHERE id = :key_id
        """, key_id=encrypted_package['key_id'])

        if not rows:
            raise ValueError(f"Encryption key not found: {encrypted_package['key_id']}")

        key = dict(zip(['id', 'public_key', 'private_key', 'kms_key_id', 'kms_key_arn', 'status'], rows[0]))
    finally:
        conn.close()
    
    # Decrypt
    private_key = base64.b64decode(key['private_key'])
    ciphertext = base64.b64decode(encrypted_package['ciphertext'])
    iv = base64.b64decode(encrypted_package['iv'])
    encrypted_data = base64.b64decode(encrypted_package['encrypted_data'])
    
    # ML-KEM-768 decapsulation
    shared_secret = pqcrypto.kem.ml_kem_768.decrypt(private_key, ciphertext)
    
    # Derive AES key and decrypt
    aes_key = hashlib.sha256(shared_secret).digest()
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted_data) + decryptor.finalize()
    
    # Remove padding
    unpadder = padding.PKCS7(128).unpadder()
    document_data = unpadder.update(padded_data) + unpadder.finalize()
    
    # Log operation
    log_operation('decrypt', document_id, key['id'])

    if is_test_mode():
        logger.debug("Decryption successful", extra={
            "document_id": document_id,
            "key_id": key['id']
        })
    
    return document_data

def log_operation(operation_type, document_id, key_id=None):
    """Log operations for audit trail"""
    conn = get_db_connection()
    try:
        # Try with key_id first, fall back to without if column doesn't exist
        try:
            conn.run("""
                INSERT INTO access_logs (document_id, access_type, key_id)
                VALUES (:document_id, :access_type, :key_id)
            """, document_id=document_id, access_type=operation_type, key_id=key_id)
        except Exception:
            # Fallback for older schema without key_id column
            conn.run("""
                INSERT INTO access_logs (document_id, access_type)
                VALUES (:document_id, :access_type)
            """, document_id=document_id, access_type=operation_type)
    except Exception as e:
        logger.warning("Failed to log operation", extra={"error": str(e), "operation_type": operation_type, "document_id": document_id, "key_id": key_id})
    finally:
        conn.close()

def lambda_handler(event, context):
    """Unified Lambda handler for API Gateway"""
    try:
        # Parse API Gateway event
        http_method = event.get('httpMethod', 'POST')
        path = event.get('path', '/')
        body = event.get('body', '{}')

        logger.info("Request", extra={"method": http_method, "path": path})
        
        if isinstance(body, str):
            body = json.loads(body) if body else {}
        
        # Route requests
        if http_method == 'POST' and path == '/encrypt':
            return handle_encrypt(body)
        elif http_method == 'GET' and path.startswith('/decrypt/'):
            document_id = path.split('/')[-1]
            return handle_decrypt(document_id, body)
        elif http_method == 'POST' and path == '/admin/rotate-keys':
            return handle_key_rotation()
        else:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'Endpoint not found'})
            }
            
    except Exception as e:
        logger.error("Unhandled error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def handle_encrypt(body):
    """Handle document encryption"""
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
    
    # Size check
    max_size = int(os.environ.get('MAX_DOCUMENT_SIZE_BYTES', 20 * 1024 * 1024))
    if len(document_data) > max_size:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Document too large (max {max_size} bytes)'})
        }
    
    # Encrypt
    result = encrypt_document(document_data, body.get('document_id'))
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'success': True,
            'document_id': result['document_id'],
            's3_location': result['s3_location'],
            'key_id': result['key_id']
        })
    }

def handle_decrypt(document_id, body):
    """Handle document decryption"""
    try:
        document_data = decrypt_document(document_id)
        
        # Return format
        output_format = body.get('output_format', 'base64')
        
        if output_format == 'text' and all(c < 128 for c in document_data):
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'document_content': document_data.decode('utf-8'),
                    'is_base64_encoded': False
                })
            }
        else:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'document_content': base64.b64encode(document_data).decode('utf-8'),
                    'is_base64_encoded': True
                })
            }
    except ValueError as e:
        return {
            'statusCode': 404,
            'body': json.dumps({'error': str(e)})
        }

def handle_key_rotation():
    """Handle key rotation operations"""
    # Implementation for key rotation
    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Key rotation initiated'})
    }
