-- Create the tables for the PQFile document storage and encryption system

-- Table to store encryption keys in a centralized pool
CREATE TABLE encryption_keys (
    id SERIAL PRIMARY KEY,
    public_key TEXT NOT NULL,
    private_key TEXT NOT NULL,
    kms_key_id VARCHAR(255),
    kms_key_arn VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_rotated_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, inactive, rotation_queued
    usage_count INT DEFAULT 0,
    CONSTRAINT status_check CHECK (status IN ('active', 'inactive', 'rotation_queued'))
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

-- Table for document access logs
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(255) NOT NULL,
    access_type VARCHAR(50) NOT NULL, -- 'upload', 'download'
    accessed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

-- Table for key rotation queue/history
CREATE TABLE key_rotations (
    id SERIAL PRIMARY KEY,
    old_key_id INT NOT NULL,
    new_key_id INT NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, in_progress, completed, failed
    FOREIGN KEY (old_key_id) REFERENCES encryption_keys(id),
    FOREIGN KEY (new_key_id) REFERENCES encryption_keys(id),
    CONSTRAINT rotation_status_check CHECK (status IN ('pending', 'in_progress', 'completed', 'failed'))
);

-- Index for faster queries on document status
CREATE INDEX idx_documents_status ON documents(status);

-- Index for faster queries on key status
CREATE INDEX idx_keys_status ON encryption_keys(status);

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
          (k.last_rotated_at IS NULL OR 
           k.last_rotated_at < CURRENT_TIMESTAMP - INTERVAL '30 days');
END;
$$ LANGUAGE plpgsql;
