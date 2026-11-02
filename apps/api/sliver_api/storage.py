"""Private object storage, with an explicit in-memory adapter for isolated tests."""

from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class S3Store:
    def __init__(self, settings: Settings):
        if not settings.s3_access_key_id or not settings.s3_secret_access_key:
            raise RuntimeError("Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.")
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=5, read_timeout=10,
                          retries={"max_attempts": 2}),
        )

    def initialize(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            options = {} if self.client.meta.region_name == "us-east-1" else {
                "CreateBucketConfiguration": {"LocationConstraint": self.client.meta.region_name}
            }
            self.client.create_bucket(Bucket=self.bucket, **options)
        # No public policy, ACL, presigned URL, or browser bucket access is created.

    def put(self, key: str, body: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body,
                               ContentType="text/csv", IfNoneMatch="*")

    def get(self, key: str) -> bytes:
        result = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            return result["Body"].read()
        finally:
            result["Body"].close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class MemoryStore:
    """Tests inject this adapter; application configuration cannot select it."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        if key in self.objects:
            raise ValueError("Objects are immutable")
        self.objects[key] = body

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
