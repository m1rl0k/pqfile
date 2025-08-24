import os
import logging
from typing import Any, Dict

import pg8000.native
import boto3
from botocore.config import Config as BotoConfig


# Logging setup
_logger_initialized = False

def get_logger(name: str = __name__) -> logging.Logger:
    global _logger_initialized
    if not _logger_initialized:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        _logger_initialized = True
    return logging.getLogger(name)


def is_test_mode() -> bool:
    return os.getenv("TEST_MODE", "false").lower() == "true"


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


# Database configuration and connection

def get_db_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "database": os.getenv("DB_NAME", "pqfile_db"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", "postgres"),
    }


def get_db_connection() -> pg8000.native.Connection:
    cfg = get_db_config()
    return pg8000.native.Connection(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
    )


# AWS clients

def _boto3_base_config(addressing_style: str = "virtual") -> BotoConfig:
    return BotoConfig(
        connect_timeout=5,
        read_timeout=20,
        retries={"max_attempts": 5, "mode": "standard"},
        signature_version="v4",
        s3={"addressing_style": addressing_style},
    )


def get_boto3_client(service_name: str):
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    endpoint_url = None

    # Prefer explicit LOCALSTACK_ENDPOINT_URL, else enable for TEST_MODE
    localstack_env = os.getenv("LOCALSTACK_ENDPOINT_URL") or os.getenv("LOCALSTACK_ENDPOINT")
    if localstack_env:
        endpoint_url = localstack_env
    elif is_test_mode():
        endpoint_url = "http://localhost:4566"

    if endpoint_url:
        # Use path-style addressing with LocalStack to avoid *.localhost hostnames
        return boto3.client(
            service_name,
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            config=_boto3_base_config(addressing_style="path"),
        )
    else:
        return boto3.client(service_name, region_name=region, config=_boto3_base_config(addressing_style="virtual"))


def get_s3_bucket() -> str:
    return os.getenv("S3_BUCKET", "documents")

