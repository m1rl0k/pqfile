import os
import base64
import pg8000.native
import pqcrypto.kem.ml_kem_768


def get_db_connection():
    return pg8000.native.Connection(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        database=os.getenv('DB_NAME', 'pqfile_db'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgres'),
    )


def create_key(conn):
    public_key, private_key = pqcrypto.kem.ml_kem_768.generate_keypair()
    public_key_b64 = base64.b64encode(public_key).decode('utf-8')
    private_key_b64 = base64.b64encode(private_key).decode('utf-8')

    rows = conn.run(
        """
        INSERT INTO encryption_keys (public_key, private_key, status, usage_count)
        VALUES (:public_key, :private_key, 'active', 0)
        RETURNING id
        """,
        public_key=public_key_b64,
        private_key=private_key_b64,
    )
    return rows[0][0]


def rotate_keys(conn):
    ROTATE_AGE_DAYS = int(os.getenv('ROTATE_AGE_DAYS', '30'))
    MIN_ACTIVE_KEYS = int(os.getenv('MIN_ACTIVE_KEYS', '3'))
    DEACTIVATE_AFTER_DAYS = int(os.getenv('DEACTIVATE_AFTER_DAYS', '60'))

    # Queue rotation for keys older than ROTATE_AGE_DAYS or above a usage threshold
    conn.run(
        f"""
        UPDATE encryption_keys
        SET status = 'rotation_queued'
        WHERE status = 'active' AND (
            created_at < CURRENT_TIMESTAMP - INTERVAL '{ROTATE_AGE_DAYS} days'
            OR usage_count >= 1000
        )
        """
    )

    # Ensure minimum active pool size
    rows = conn.run("SELECT COUNT(*) FROM encryption_keys WHERE status = 'active'")
    active_count = rows[0][0]
    if active_count < MIN_ACTIVE_KEYS:
        for _ in range(MIN_ACTIVE_KEYS - active_count):
            create_key(conn)

    # Deactivate keys that have been queued for longer than DEACTIVATE_AFTER_DAYS
    conn.run(
        f"""
        UPDATE encryption_keys
        SET status = 'expired'
        WHERE status = 'rotation_queued'
          AND created_at < CURRENT_TIMESTAMP - INTERVAL '{DEACTIVATE_AFTER_DAYS} days'
        """
    )


def lambda_handler(event, context):
    conn = get_db_connection()
    try:
        rotate_keys(conn)
        # Emit CloudWatch metric for active keys after rotation
        rows = conn.run("SELECT COUNT(*) FROM encryption_keys WHERE status = 'active'")
        active_count = rows[0][0]
        # Dimensions are omitted; MetricFilter/Embedded metrics format would be ideal, but keep it simple:
        print(f"METRIC::PQFile/Keys::ActiveKeysCount::{active_count}")
        return {
            'statusCode': 200,
            'body': 'Rotation complete'
        }
    except Exception as e:
        print(f"METRIC::PQFile/Keys::RotationErrors::1")
        raise
    finally:
        conn.close()

