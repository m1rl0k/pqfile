#!/usr/bin/env python3
"""
Simple test to check if pqcrypto decrypt works with pre-generated data
"""

import base64

# These are known good ML-KEM-768 test vectors (if available)
# For now, let's test if we can at least import and check constants

def test_pqcrypto_basic():
    """Test basic pqcrypto functionality"""
    try:
        import pqcrypto.kem.ml_kem_768 as kyber
        print("✅ pqcrypto.kem.ml_kem_768 imported successfully")
        
        print(f"PUBLIC_KEY_SIZE: {kyber.PUBLIC_KEY_SIZE}")
        print(f"SECRET_KEY_SIZE: {kyber.SECRET_KEY_SIZE}")
        print(f"CIPHERTEXT_SIZE: {kyber.CIPHERTEXT_SIZE}")
        
        # Test if we can call the functions without hanging
        print("Testing function availability...")
        print(f"generate_keypair available: {hasattr(kyber, 'generate_keypair')}")
        print(f"encrypt available: {hasattr(kyber, 'encrypt')}")
        print(f"decrypt available: {hasattr(kyber, 'decrypt')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_with_dummy_data():
    """Test with dummy data to see where it fails"""
    try:
        import pqcrypto.kem.ml_kem_768 as kyber
        
        # Create dummy data with correct sizes
        dummy_public = b'A' * kyber.PUBLIC_KEY_SIZE
        dummy_private = b'B' * kyber.SECRET_KEY_SIZE
        dummy_ciphertext = b'C' * kyber.CIPHERTEXT_SIZE
        
        print(f"Created dummy data: pub={len(dummy_public)}, priv={len(dummy_private)}, ct={len(dummy_ciphertext)}")
        
        # Try encrypt with dummy public key
        try:
            ct, secret = kyber.encrypt(dummy_public)
            print("❌ Encrypt with dummy key should have failed but didn't")
        except Exception as e:
            print(f"✅ Encrypt with dummy key failed as expected: {e}")
        
        # Try decrypt with dummy private key
        try:
            secret = kyber.decrypt(dummy_ciphertext, dummy_private)
            print("❌ Decrypt with dummy key should have failed but didn't")
        except Exception as e:
            print(f"✅ Decrypt with dummy key failed as expected: {e}")
            
        return True
        
    except Exception as e:
        print(f"❌ Error in dummy test: {e}")
        return False

if __name__ == '__main__':
    print("🔐 Testing pqcrypto ML-KEM-768 Basic Functionality")
    print("=" * 60)
    
    if test_pqcrypto_basic():
        print("\n" + "=" * 60)
        test_with_dummy_data()
    
    print("\nTest completed.")
