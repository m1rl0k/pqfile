# PQFile - Post-Quantum Cryptography Document System

A local development environment for a post-quantum cryptography document system with PostgreSQL for key management and state machine functionality. This system manages a pool of encryption keys, handles rotation, and provides Lambda functions for document encryption and decryption.

## Overview

This project sets up:

1. A PostgreSQL database for key management and document metadata
2. A LocalStack container with S3 and KMS services for storage and key management
3. Two Lambda functions:
   - `store_lambda`: Encrypts documents and handles key management
   - `retrieve_lambda`: Decrypts and returns documents

## Features

- Post-quantum cryptography for document encryption (simulated Kyber768)
- Key rotation for documents older than 30 days
- Integration with AWS KMS for public key management
- Support for documents up to 100MB (configurable, default 20MB)
- Audit logging for document access

## Setup Instructions

### Prerequisites

- Docker and Docker Compose
- Python 3.8+
- AWS CLI (for interacting with LocalStack)

### Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd pqfile
   ```

2. Start the containers:
   ```
   docker-compose up -d
   ```

3. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create the S3 bucket in LocalStack:
   ```
   aws --endpoint-url=http://localhost:4566 s3 mb s3://documents
   ```

### Lambda Functions

#### Store Lambda

The store lambda encrypts documents using post-quantum cryptography:

```python
import requests
import json
import base64

# Example usage
url = "http://localhost:9000/2015-03-31/functions/store_lambda/invocations"
document_content = "This is a secret document."
payload = {
    "body": {
        "content": document_content,
        "filename": "secret.txt",
        "contentType": "text/plain"
    }
}
response = requests.post(url, json=payload)
encrypted_package = json.loads(response.json()["body"])
print(encrypted_package)
```

#### Retrieve Lambda

The retrieve lambda decrypts documents:

```python
import requests
import json
import base64

# Example usage - takes the encrypted_package from the store lambda
url = "http://localhost:9000/2015-03-31/functions/retrieve_lambda/invocations"
payload = {
    "body": {
        "encrypted_package": encrypted_package,
        "output_format": "text"
    }
}
response = requests.post(url, json=payload)
result = json.loads(response.json()["body"])
if result["is_base64_encoded"]:
    document = base64.b64decode(result["document_content"]).decode('utf-8')
else:
    document = result["document_content"]
print(document)
```

### Key Rotation

To check for keys that need rotation (older than 30 days):

```python
import requests
import json

url = "http://localhost:9000/2015-03-31/functions/store_lambda/invocations"
payload = {
    "operation": "check_for_keys_to_rotate"
}
response = requests.post(url, json=payload)
print(json.loads(response.json()["body"]))
```

## Database Schema

The database has the following key tables:

1. `encryption_keys`: Stores the key pairs and their status
2. `documents`: Stores document metadata and links to encryption keys
3. `access_logs`: Tracks document access
4. `key_rotations`: Manages key rotation processes

## Configuration

Environment variables can be used to configure the system:

- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: Database connection
- `MAX_DOCUMENT_SIZE_BYTES`: Maximum document size (default: 20MB)
- `KMS_ENDPOINT_URL`, `S3_ENDPOINT_URL`: LocalStack service endpoints
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: AWS credentials

## Notes

- This is a development environment using LocalStack for AWS services.
- In a production environment, you would use a proper post-quantum cryptography library.
- The system is designed to handle a pool of approximately 100 keys shared across all documents.
