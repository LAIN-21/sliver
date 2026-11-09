"""Private object storage (ADR 0002), with an in-memory adapter for isolated tests."""

import logging
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import Settings

logger = logging.getLogger(__name__)


class ObjectExistsError(Exception):
    """Stored objects are immutable; a key can only be written once."""


class ObjectStore(Protocol):
    def initialize(self) -> None: ...
    def ready(self) -> bool: ...
    def put(self, key: str, body: bytes, content_type: str = "text/csv") -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class S3Store:
    def __init__(self, settings: Settings):
        if not settings.s3_access_key_id or not settings.s3_secret_access_key:
            raise ValueError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required")
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    def initialize(self) -> None:
        """Create the private bucket if it does not exist. No public policy is ever attached."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
        options = {}
        if self.region != "us-east-1":
            options["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
        self.client.create_bucket(Bucket=self.bucket, **options)
        logger.info("created private bucket %s", self.bucket)

    def ready(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False

    def put(self, key: str, body: bytes, content_type: str = "text/csv") -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, IfNoneMatch="*"
            )
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
                raise ObjectExistsError(key) from None
            raise

    def get(self, key: str) -> bytes:
        result = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            return result["Body"].read()
        finally:
            result["Body"].close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class MemoryStore:
    """Injected by tests only; runtime configuration cannot select it."""

    def __init__(self, healthy: bool = True):
        self.objects: dict[str, bytes] = {}
        self.healthy = healthy

    def initialize(self) -> None:
        return None

    def ready(self) -> bool:
        return self.healthy

    def put(self, key: str, body: bytes, content_type: str = "text/csv") -> None:
        if key in self.objects:
            raise ObjectExistsError(key)
        self.objects[key] = bytes(body)

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
