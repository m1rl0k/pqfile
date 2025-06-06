#!/usr/bin/env python3
"""
Test ML-KEM-768 encryption/decryption cycle
"""

import base64
import hashlib
import pqcrypto.kem.ml_kem_768
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

def test_kyber_cycle():
    """Test the complete ML-KEM-768 + AES encryption/decryption cycle"""
    
    print("🔐 Testing ML-KEM-768 + AES Encryption/Decryption Cycle")
    print("=" * 60)
    
    # Test data
    test_data = b"This is a test document for encryption and decryption. It needs to be exactly 100 characters to test properly.AAAAAAAAAAAAAAAAAAAAAA"
    print(f"Original data: {test_data}")
    print(f"Original length: {len(test_data)} bytes")
    print()
    
    # Step 1: Generate key pair
    print("Step 1: Generating ML-KEM-768 key pair...")
    public_key, private_key = pqcrypto.kem.ml_kem_768.generate_keypair()
    print(f"Public key length: {len(public_key)} bytes")
    print(f"Private key length: {len(private_key)} bytes")
    print()
    
    # Step 2: Encrypt (encapsulate)
    print("Step 2: Encrypting with ML-KEM-768...")
    ciphertext, shared_secret = pqcrypto.kem.ml_kem_768.encrypt(public_key)
    print(f"Ciphertext length: {len(ciphertext)} bytes")
    print(f"Shared secret length: {len(shared_secret)} bytes")
    
    # Convert shared secret to AES key
    aes_key = hashlib.sha256(shared_secret).digest()
    print(f"AES key length: {len(aes_key)} bytes")
    print()
    
    # Step 3: AES encryption
    print("Step 3: Encrypting data with AES...")
    iv = b"1234567890123456"  # 16 bytes for testing
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(test_data) + padder.finalize()
    
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    print(f"Encrypted data length: {len(encrypted_data)} bytes")
    print()
    
    # Step 4: Decrypt (decapsulate)
    print("Step 4: Decrypting with ML-KEM-768...")
    recovered_shared_secret = pqcrypto.kem.ml_kem_768.decrypt(ciphertext, private_key)
    print(f"Recovered shared secret length: {len(recovered_shared_secret)} bytes")
    
    # Convert to AES key
    recovered_aes_key = hashlib.sha256(recovered_shared_secret).digest()
    print(f"Recovered AES key length: {len(recovered_aes_key)} bytes")
    
    # Check if shared secrets match
    if shared_secret == recovered_shared_secret:
        print("✅ Shared secrets match!")
    else:
        print("❌ Shared secrets don't match!")
        return False
    print()
    
    # Step 5: AES decryption
    print("Step 5: Decrypting data with AES...")
    cipher = Cipher(algorithms.AES(recovered_aes_key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
    
    # Remove padding
    unpadder = padding.PKCS7(128).unpadder()
    decrypted_data = unpadder.update(decrypted_padded) + unpadder.finalize()
    
    print(f"Decrypted data: {decrypted_data}")
    print(f"Decrypted length: {len(decrypted_data)} bytes")
    print()
    
    # Step 6: Verify
    print("Step 6: Verification...")
    if test_data == decrypted_data:
        print("✅ SUCCESS: Encryption/Decryption cycle completed successfully!")
        return True
    else:
        print("❌ FAILURE: Decrypted data doesn't match original!")
        print(f"Expected: {test_data}")
        print(f"Got:      {decrypted_data}")
        return False

if __name__ == '__main__':
    success = test_kyber_cycle()
    exit(0 if success else 1)
