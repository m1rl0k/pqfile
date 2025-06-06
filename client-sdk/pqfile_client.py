"""
PQFile Client SDK
Simple Python client for the PQFile document encryption API
"""

import requests
import json
import base64
from typing import Optional, Union


class PQFileClient:
    """Client for PQFile document encryption service"""
    
    def __init__(self, api_endpoint: str, api_key: Optional[str] = None):
        """
        Initialize PQFile client
        
        Args:
            api_endpoint: Base URL of the PQFile API
            api_key: Optional API key for authentication (future use)
        """
        self.api_endpoint = api_endpoint.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
        if api_key:
            self.session.headers.update({'Authorization': f'Bearer {api_key}'})
    
    def encrypt_document(self, content: Union[str, bytes], document_id: Optional[str] = None) -> dict:
        """
        Encrypt a document
        
        Args:
            content: Document content (string or bytes)
            document_id: Optional custom document ID
            
        Returns:
            dict: Response containing document_id, s3_location, and key_id
            
        Raises:
            PQFileError: If encryption fails
        """
        # Prepare payload
        payload = {}
        
        if isinstance(content, str):
            payload['content'] = content
            payload['isBase64Encoded'] = False
        elif isinstance(content, bytes):
            payload['content'] = base64.b64encode(content).decode('utf-8')
            payload['isBase64Encoded'] = True
        else:
            raise ValueError("Content must be string or bytes")
        
        if document_id:
            payload['document_id'] = document_id
        
        # Make request
        response = self.session.post(
            f"{self.api_endpoint}/encrypt",
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code != 200:
            raise PQFileError(f"Encryption failed: {response.text}")
        
        return response.json()
    
    def decrypt_document(self, document_id: str, output_format: str = 'auto') -> Union[str, bytes]:
        """
        Decrypt a document
        
        Args:
            document_id: Document ID to decrypt
            output_format: 'text', 'bytes', or 'auto' (default)
            
        Returns:
            Document content as string or bytes
            
        Raises:
            PQFileError: If decryption fails
        """
        # Make request
        payload = {'output_format': 'base64' if output_format == 'bytes' else 'text'}
        
        response = self.session.get(
            f"{self.api_endpoint}/decrypt/{document_id}",
            json=payload
        )
        
        if response.status_code == 404:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        elif response.status_code != 200:
            raise PQFileError(f"Decryption failed: {response.text}")
        
        result = response.json()
        content = result['document_content']
        is_base64 = result.get('is_base64_encoded', False)
        
        if output_format == 'bytes' or (output_format == 'auto' and is_base64):
            return base64.b64decode(content)
        else:
            return content
    
    def rotate_keys(self) -> dict:
        """
        Initiate key rotation (admin operation)
        
        Returns:
            dict: Rotation status
            
        Raises:
            PQFileError: If rotation fails
        """
        response = self.session.post(f"{self.api_endpoint}/admin/rotate-keys")
        
        if response.status_code != 200:
            raise PQFileError(f"Key rotation failed: {response.text}")
        
        return response.json()
    
    def health_check(self) -> bool:
        """
        Check if the API is healthy
        
        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Try a simple request to see if API is responding
            response = self.session.get(f"{self.api_endpoint}/")
            return response.status_code in [200, 404]  # 404 is fine, means API is up
        except:
            return False


class PQFileError(Exception):
    """Base exception for PQFile operations"""
    pass


class DocumentNotFoundError(PQFileError):
    """Raised when a document is not found"""
    pass


# Example usage
if __name__ == "__main__":
    # Example usage
    client = PQFileClient("https://your-api-gateway-url.amazonaws.com/dev")
    
    # Encrypt a document
    try:
        result = client.encrypt_document("This is a secret document!")
        print(f"Document encrypted: {result['document_id']}")
        
        # Decrypt the document
        decrypted = client.decrypt_document(result['document_id'])
        print(f"Decrypted content: {decrypted}")
        
    except PQFileError as e:
        print(f"Error: {e}")
