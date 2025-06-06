import os
import json
import boto3
import pg8000.native
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

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

# Simulating Kyber constants for example purposes
KYBER_CIPHERTEXT_SIZE = 1088
KYBER_SHARED_SECRET_SIZE = 32

def get_key_by_id(key_id):
    """Retrieve encryption key by ID"""
    conn = get_db_connection()
    try:
        rows = conn.run("""
            SELECT id, public_key, private_key, kms_key_id, kms_key_arn, status
            FROM encryption_keys
            WHERE id = :key_id
        """, key_id=key_id)

        if not rows:
            raise ValueError(f"Key with ID {key_id} not found")

        key = dict(zip(['id', 'public_key', 'private_key', 'kms_key_id', 'kms_key_arn', 'status'], rows[0]))

        if key['status'] != 'active' and key['status'] != 'rotation_queued':
            raise ValueError(f"Key with ID {key_id} is not active (status: {key['status']})")

        return key
    finally:
        conn.close()

def log_document_access(document_id):
    """Log document access for audit and tracking purposes"""
    conn = get_db_connection()
    try:
        conn.run("""
            INSERT INTO access_logs (document_id, access_type)
            VALUES (:document_id, 'download')
        """, document_id=document_id)
    finally:
        conn.close()

def decrypt_document(encrypted_package):
    """Decrypt a document that was encrypted with post-quantum cryptography"""
    # Extract components from the encrypted package
    key_id = encrypted_package.get('key_id')
    if not key_id:
        raise ValueError("Missing key_id in encrypted package")
        
    ciphertext_b64 = encrypted_package.get('ciphertext')
    if not ciphertext_b64:
        raise ValueError("Missing ciphertext in encrypted package")
    
    iv_b64 = encrypted_package.get('iv')
    if not iv_b64:
        raise ValueError("Missing initialization vector (iv) in encrypted package")
    
    encrypted_data_b64 = encrypted_package.get('encrypted_data')
    if not encrypted_data_b64:
        raise ValueError("Missing encrypted_data in encrypted package")
    
    # Decode from base64
    ciphertext = base64.b64decode(ciphertext_b64)
    iv = base64.b64decode(iv_b64)
    encrypted_data = base64.b64decode(encrypted_data_b64)
    
    # Get the key from the database
    key = get_key_by_id(key_id)
    
    # Load private key
    private_key = base64.b64decode(key['private_key'])
    
    # In a real implementation:
    # shared_secret = pqcrypto.kem.kyber.Kyber768.decapsulate(ciphertext, private_key)
    
    # For this example, we'll simulate the decapsulation
    public_key = base64.b64decode(key['public_key'])
    shared_secret = hashlib.sha256(ciphertext + public_key).digest()
    
    # Convert shared secret to an AES key
    aes_key = hashlib.sha256(shared_secret).digest()
    
    # Use AES to decrypt the document data
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted_data) + decryptor.finalize()
    
    # Remove padding
    unpadder = padding.PKCS7(128).unpadder()
    document_data = unpadder.update(padded_data) + unpadder.finalize()
    
    # If a document_id is provided, log the access
    document_id = encrypted_package.get('metadata', {}).get('document_id')
    if document_id:
        log_document_access(document_id)
    
    return document_data

def lambda_handler(event, context):
    """AWS Lambda entry point"""
    try:
        # Get encrypted package from the request
        if 'body' not in event:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing encrypted package'})
            }
        
        # Parse the body content
        body = event['body']
        if isinstance(body, str):
            body = json.loads(body)
            
        # Get the encrypted package
        encrypted_package = body.get('encrypted_package')
        if not encrypted_package:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing encrypted_package in request body'})
            }
        
        # Decrypt the document
        document_data = decrypt_document(encrypted_package)
        
        # Check output format preference
        output_format = body.get('output_format', 'base64')
        
        result = {
            'success': True,
            'document_size': len(document_data)
        }
        
        # Return the document based on output format preference
        if output_format == 'base64':
            result['document_content'] = base64.b64encode(document_data).decode('utf-8')
            result['is_base64_encoded'] = True
        elif output_format == 'text' and all(c < 128 for c in document_data):
            # Only decode as text if all bytes are ASCII
            result['document_content'] = document_data.decode('utf-8')
            result['is_base64_encoded'] = False
        else:
            # Default to base64 for binary data or unknown format
            result['document_content'] = base64.b64encode(document_data).decode('utf-8')
            result['is_base64_encoded'] = True
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

# For local testing
if __name__ == '__main__':
    # This would accept an encrypted package from the store_lambda for testing
    # encrypt_result = {...}  # Result from encrypt_document
    # decrypted_data = decrypt_document(encrypt_result)
    # print(decrypted_data.decode('utf-8'))
    pass