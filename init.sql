-- Create the tables for the PQFile document storage and encryption system

-- Table to store encryption keys in a centralized pool
CREATE TABLE encryption_keys (
    id SERIAL PRIMARY KEY,
    public_key TEXT NOT NULL,
    private_key TEXT NOT NULL,
    kms_key_id TEXT,
    kms_key_arn TEXT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    usage_count INTEGER DEFAULT 0,
    CONSTRAINT status_check CHECK (status IN ('active', 'rotation_queued', 'expired', 'revoked'))
);

-- Table to store document metadata
CREATE TABLE documents (
    id VARCHAR(255) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL, 
    key_id INT NOT NULL,
    s3_key VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, inactive
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    FOREIGN KEY (key_id) REFERENCES encryption_keys(id),
    CONSTRAINT doc_status_check CHECK (status IN ('active', 'inactive'))
);

-- Table for document access logs (no foreign key constraint for flexibility)
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    access_type VARCHAR(50) NOT NULL, -- 'encrypt', 'decrypt', 'upload', 'download'
    accessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    ip_address INET,
    user_agent TEXT,
    key_id INTEGER REFERENCES encryption_keys(id)
);

-- Table for key rotation queue/history
CREATE TABLE key_rotations (
    id SERIAL PRIMARY KEY,
    old_key_id INTEGER REFERENCES encryption_keys(id),
    new_key_id INTEGER REFERENCES encryption_keys(id),
    status VARCHAR(20) DEFAULT 'pending',
    initiated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    CONSTRAINT rotation_status_check CHECK (status IN ('pending', 'in_progress', 'completed', 'failed'))
);

-- Index for faster queries on document status
CREATE INDEX idx_documents_status ON documents(status);

-- Index for faster queries on key status
CREATE INDEX idx_keys_status ON encryption_keys(status);

-- Additional indexes for performance
CREATE INDEX idx_encryption_keys_usage_count ON encryption_keys(usage_count);
CREATE INDEX idx_encryption_keys_created_at ON encryption_keys(created_at);
CREATE INDEX idx_access_logs_timestamp ON access_logs(accessed_at);
CREATE INDEX idx_access_logs_document_id ON access_logs(document_id);
CREATE INDEX idx_access_logs_access_type ON access_logs(access_type);
CREATE INDEX idx_key_rotations_status ON key_rotations(status);

-- Function to automatically update last_accessed_at when a document is downloaded
CREATE OR REPLACE FUNCTION update_document_last_accessed()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE documents
    SET last_accessed_at = CURRENT_TIMESTAMP
    WHERE id = NEW.document_id AND NEW.access_type = 'download';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update last_accessed_at timestamp
CREATE TRIGGER update_document_access_time
AFTER INSERT ON access_logs
FOR EACH ROW
EXECUTE FUNCTION update_document_last_accessed();

-- Function to increment usage count when a key is used
CREATE OR REPLACE FUNCTION increment_key_usage()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE encryption_keys
    SET usage_count = usage_count + 1
    WHERE id = NEW.key_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to increment key usage count
CREATE TRIGGER increment_key_usage_count
AFTER INSERT ON documents
FOR EACH ROW
EXECUTE FUNCTION increment_key_usage();

-- Function to find keys that need rotation (older than 30 days)
CREATE OR REPLACE FUNCTION find_keys_for_rotation()
RETURNS TABLE (key_id INT) AS $$
BEGIN
    RETURN QUERY
    SELECT k.id
    FROM encryption_keys k
    WHERE k.status = 'active' AND
          k.created_at < CURRENT_TIMESTAMP - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;

-- Insert a sample encryption key for initial testing
-- This will be replaced by actual key generation in production
INSERT INTO encryption_keys (public_key, private_key, kms_key_id, kms_key_arn, status, usage_count)
VALUES (
    -- Sample Base64-encoded public key (1184 bytes for Kyber768)
    encode(gen_random_bytes(1184), 'base64'),
    -- Sample Base64-encoded private key (2400 bytes for Kyber768)
    encode(gen_random_bytes(2400), 'base64'),
    -- Sample KMS key ID
    'sample-kms-key-' || gen_random_uuid()::text,
    -- Sample KMS key ARN
    'arn:aws:kms:us-east-1:123456789012:key/sample-' || gen_random_uuid()::text,
    'active',
    0
);
