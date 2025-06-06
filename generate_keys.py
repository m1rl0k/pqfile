#!/usr/bin/env python3
"""
Generate additional encryption keys for the PQFile system
"""

import os
import base64
import hashlib
import datetime
import pg8000.native
import boto3
import pqcrypto.kem.ml_kem_768

# Real Kyber768 constants
KYBER_PUBLIC_KEY_SIZE = 1184
KYBER_PRIVATE_KEY_SIZE = 2400

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'pqfile_db',
    'user': 'postgres',
    'password': 'postgres'
}

def get_db_connection():
    """Get a database connection"""
    return pg8000.native.Connection(**DB_CONFIG)

def generate_secure_key_pair():
    """Generate a real ML-KEM-768 (Kyber768) key pair for post-quantum security"""
    # Generate a real ML-KEM-768 key pair
    public_key, private_key = pqcrypto.kem.ml_kem_768.generate_keypair()

    return public_key, private_key

def create_kms_key():
    """Create a KMS key for additional security"""
    try:
        # Configure KMS client for LocalStack
        kms_client = boto3.client(
            'kms',
            endpoint_url='http://localhost:4566',
            aws_access_key_id='test',
            aws_secret_access_key='test',
            region_name='us-east-1'
        )
        
        # Create KMS key
        response = kms_client.create_key(
            Description=f'PQFile Encryption Key - {datetime.datetime.now().isoformat()}',
            KeyUsage='ENCRYPT_DECRYPT',
            Origin='AWS_KMS',
            Tags=[
                {
                    'TagKey': 'Purpose',
                    'TagValue': 'PQCrypto'
                },
                {
                    'TagKey': 'System',
                    'TagValue': 'PQFile'
                }
            ]
        )
        
        return response['KeyMetadata']['KeyId'], response['KeyMetadata']['Arn']
    except Exception as e:
        print(f"Warning: Could not create KMS key: {e}")
        return None, None

def store_key_in_database(public_key, private_key, kms_key_id, kms_key_arn):
    """Store the key pair in the database"""
    conn = get_db_connection()
    try:
        # Encode keys to base64 for storage
        public_key_b64 = base64.b64encode(public_key).decode('utf-8')
        private_key_b64 = base64.b64encode(private_key).decode('utf-8')
        
        # Insert the key into the database
        rows = conn.run("""
            INSERT INTO encryption_keys
            (public_key, private_key, kms_key_id, kms_key_arn, status, usage_count)
            VALUES (:public_key, :private_key, :kms_key_id, :kms_key_arn, 'active', 0)
            RETURNING id, created_at
        """, public_key=public_key_b64, private_key=private_key_b64,
             kms_key_id=kms_key_id, kms_key_arn=kms_key_arn)
        
        key_id, created_at = rows[0]
        return key_id, created_at
    finally:
        conn.close()

def generate_multiple_keys(count=5):
    """Generate multiple encryption keys"""
    print(f"Generating {count} encryption keys...")
    
    generated_keys = []
    
    for i in range(count):
        print(f"Generating key {i+1}/{count}...")
        
        # Generate key pair
        public_key, private_key = generate_secure_key_pair()
        
        # Create KMS key
        kms_key_id, kms_key_arn = create_kms_key()
        
        # Store in database
        key_id, created_at = store_key_in_database(public_key, private_key, kms_key_id, kms_key_arn)
        
        generated_keys.append({
            'id': key_id,
            'created_at': created_at,
            'kms_key_id': kms_key_id,
            'public_key_size': len(public_key),
            'private_key_size': len(private_key)
        })
        
        print(f"✅ Generated key ID {key_id}")
    
    return generated_keys

def show_key_pool_status():
    """Show the current status of the key pool"""
    conn = get_db_connection()
    try:
        # Get key statistics
        rows = conn.run("""
            SELECT 
                status,
                COUNT(*) as count,
                AVG(usage_count) as avg_usage,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM encryption_keys 
            GROUP BY status
            ORDER BY status
        """)
        
        print("\n📊 Key Pool Status:")
        print("=" * 60)
        for row in rows:
            status, count, avg_usage, oldest, newest = row
            print(f"Status: {status}")
            print(f"  Count: {count}")
            print(f"  Average Usage: {avg_usage:.1f}")
            print(f"  Oldest: {oldest}")
            print(f"  Newest: {newest}")
            print()
        
        # Get individual key details
        rows = conn.run("""
            SELECT id, status, usage_count, created_at, 
                   LENGTH(public_key) as pub_len, LENGTH(private_key) as priv_len
            FROM encryption_keys 
            ORDER BY created_at DESC
            LIMIT 10
        """)
        
        print("🔑 Recent Keys:")
        print("=" * 60)
        print("ID    Status   Usage  Created                    Pub/Priv Key Sizes")
        print("-" * 60)
        for row in rows:
            key_id, status, usage, created, pub_len, priv_len = row
            print(f"{key_id:<5} {status:<8} {usage:<6} {created} {pub_len}/{priv_len}")
        
    finally:
        conn.close()

if __name__ == '__main__':
    print("🔐 PQFile Key Generation Tool")
    print("=" * 40)
    
    # Show current status
    show_key_pool_status()
    
    # Generate new keys
    try:
        keys = generate_multiple_keys(3)
        print(f"\n✅ Successfully generated {len(keys)} new encryption keys!")
        
        # Show updated status
        print("\n📈 Updated Key Pool Status:")
        show_key_pool_status()
        
    except Exception as e:
        print(f"❌ Error generating keys: {e}")
        import traceback
        traceback.print_exc()
