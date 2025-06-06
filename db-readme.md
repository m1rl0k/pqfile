# Database Schema Documentation

## Overview

The PQFile system uses PostgreSQL to manage encryption keys, document metadata, and audit logs. The database is designed to support post-quantum cryptography key management with rotation capabilities and comprehensive audit trails.

## Database Configuration

- **Database Name**: `pqfile_db`
- **User**: `postgres`
- **Password**: `postgres`
- **Host**: `postgres` (container name) / `localhost` (external access)
- **Port**: `5432`

## Schema Tables

### 1. encryption_keys

Stores post-quantum cryptography key pairs and their lifecycle information.

```sql
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
```

#### Columns:
- `id`: Unique identifier for the key pair
- `public_key`: Base64-encoded Kyber768 public key (1184 bytes)
- `private_key`: Base64-encoded Kyber768 private key (2400 bytes)
- `kms_key_id`: AWS KMS key ID for additional security layer
- `kms_key_arn`: AWS KMS key ARN
- `status`: Key lifecycle status (`active`, `rotation_queued`, `expired`, `revoked`)
- `created_at`: Key creation timestamp
- `expires_at`: Key expiration timestamp (for rotation)
- `usage_count`: Number of times this key has been used for encryption

#### Indexes:
```sql
CREATE INDEX idx_encryption_keys_status ON encryption_keys(status);
CREATE INDEX idx_encryption_keys_usage_count ON encryption_keys(usage_count);
CREATE INDEX idx_encryption_keys_created_at ON encryption_keys(created_at);
```

### 2. access_logs

Audit trail for document access and operations.

```sql
CREATE TABLE access_logs (
    id SERIAL PRIMARY KEY,
    document_id TEXT,
    access_type VARCHAR(50),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    ip_address INET,
    user_agent TEXT,
    key_id INTEGER REFERENCES encryption_keys(id)
);
```

#### Columns:
- `id`: Unique log entry identifier
- `document_id`: Identifier for the accessed document
- `access_type`: Type of access (`encrypt`, `decrypt`, `download`, `upload`)
- `timestamp`: When the access occurred
- `user_id`: User who performed the action (future enhancement)
- `ip_address`: Source IP address (future enhancement)
- `user_agent`: Client user agent (future enhancement)
- `key_id`: Reference to the encryption key used

#### Indexes:
```sql
CREATE INDEX idx_access_logs_timestamp ON access_logs(timestamp);
CREATE INDEX idx_access_logs_document_id ON access_logs(document_id);
CREATE INDEX idx_access_logs_access_type ON access_logs(access_type);
```

### 3. key_rotations

Manages key rotation processes and schedules.

```sql
CREATE TABLE key_rotations (
    id SERIAL PRIMARY KEY,
    old_key_id INTEGER REFERENCES encryption_keys(id),
    new_key_id INTEGER REFERENCES encryption_keys(id),
    status VARCHAR(20) DEFAULT 'pending',
    initiated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
```

#### Columns:
- `id`: Unique rotation process identifier
- `old_key_id`: Key being rotated out
- `new_key_id`: New key replacing the old one
- `status`: Rotation status (`pending`, `in_progress`, `completed`, `failed`)
- `initiated_at`: When rotation was started
- `completed_at`: When rotation was finished

## Key Management Strategy

### Key Pool Management
- The system maintains a pool of approximately 100 active keys
- Keys are selected using round-robin based on `usage_count`
- New keys are automatically generated when the pool is low

### Key Rotation
- Keys older than 30 days are queued for rotation
- Rotation is triggered by the `check_for_keys_to_rotate` operation
- Old keys are marked as `rotation_queued` but remain available for decryption

### Key Lifecycle States
1. **active**: Key is available for new encryptions
2. **rotation_queued**: Key is scheduled for rotation, still usable for decryption
3. **expired**: Key has passed its expiration date
4. **revoked**: Key has been manually revoked for security reasons

## Security Considerations

### Key Storage
- Private keys are stored Base64-encoded in the database
- Additional protection via AWS KMS integration
- Database connections should use SSL/TLS in production

### Access Control
- Database access restricted to Lambda functions
- All operations logged in `access_logs` table
- Key usage tracked for audit purposes

### Backup and Recovery
- Regular database backups recommended
- Key material should be backed up securely
- Consider encrypted backup storage

## Performance Optimization

### Query Patterns
- Most common: Find active key with lowest usage count
- Frequent: Log access events
- Periodic: Check for keys needing rotation

### Recommended Maintenance
```sql
-- Clean old access logs (older than 1 year)
DELETE FROM access_logs WHERE timestamp < NOW() - INTERVAL '1 year';

-- Update key statistics
ANALYZE encryption_keys;
ANALYZE access_logs;

-- Check for unused keys
SELECT id, created_at, usage_count 
FROM encryption_keys 
WHERE usage_count = 0 AND created_at < NOW() - INTERVAL '7 days';
```

## Monitoring Queries

### Key Pool Health
```sql
-- Active key count
SELECT COUNT(*) as active_keys FROM encryption_keys WHERE status = 'active';

-- Key usage distribution
SELECT 
    usage_count,
    COUNT(*) as key_count
FROM encryption_keys 
WHERE status = 'active'
GROUP BY usage_count
ORDER BY usage_count;
```

### Access Patterns
```sql
-- Daily access volume
SELECT 
    DATE(timestamp) as access_date,
    access_type,
    COUNT(*) as access_count
FROM access_logs
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY DATE(timestamp), access_type
ORDER BY access_date DESC;
```

### Key Rotation Status
```sql
-- Pending rotations
SELECT 
    kr.id,
    kr.initiated_at,
    ek_old.created_at as old_key_created,
    ek_new.created_at as new_key_created
FROM key_rotations kr
JOIN encryption_keys ek_old ON kr.old_key_id = ek_old.id
JOIN encryption_keys ek_new ON kr.new_key_id = ek_new.id
WHERE kr.status = 'pending';
```

## Connection Examples

### Python (pg8000)
```python
import pg8000.native

conn = pg8000.native.Connection(
    host='localhost',
    port=5432,
    database='pqfile_db',
    user='postgres',
    password='postgres'
)

# Query active keys
rows = conn.run("SELECT id, usage_count FROM encryption_keys WHERE status = 'active'")
print(rows)

conn.close()
```

### psql CLI
```bash
# Connect to database
psql -h localhost -p 5432 -U postgres -d pqfile_db

# List all tables
\dt

# Describe encryption_keys table
\d encryption_keys

# Check key pool status
SELECT status, COUNT(*) FROM encryption_keys GROUP BY status;
```

## Troubleshooting

### Common Issues

1. **Connection refused**: Check if PostgreSQL container is running
2. **Permission denied**: Verify database credentials
3. **Table doesn't exist**: Run initialization script from Dockerfile

### Diagnostic Queries
```sql
-- Check database size
SELECT pg_size_pretty(pg_database_size('pqfile_db'));

-- Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public';

-- Check active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'pqfile_db';
```
