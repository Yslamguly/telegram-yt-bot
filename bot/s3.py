"""AWS S3 client for uploading and managing downloaded videos."""

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Client:
    """Thin wrapper around boto3 S3 operations."""

    def __init__(self, bucket_name: str, region: str) -> None:
        self.bucket_name = bucket_name
        self.client = boto3.client("s3", region_name=region)
        logger.info("S3 client initialized — bucket=%s, region=%s", bucket_name, region)

    def upload_file(self, filepath: str, key: str | None = None) -> str:
        """Upload a local file to S3.

        Args:
            filepath: Absolute path to the local file.
            key: S3 object key. Defaults to the file's basename.

        Returns:
            The S3 object key.
        """
        if key is None:
            key = os.path.basename(filepath)
        try:
            self.client.upload_file(filepath, self.bucket_name, key)
            logger.info("Uploaded %s → s3://%s/%s", filepath, self.bucket_name, key)
            return key
        except ClientError:
            logger.exception("Failed to upload %s to S3", filepath)
            raise

    def delete_file(self, key: str) -> bool:
        """Delete an object from S3.

        Returns:
            ``True`` if the deletion succeeded, ``False`` otherwise.
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info("Deleted s3://%s/%s", self.bucket_name, key)
            return True
        except ClientError:
            logger.exception("Failed to delete s3://%s/%s", self.bucket_name, key)
            return False

    def list_objects(self, prefix: str = "") -> list[dict[str, Any]]:
        """List objects in the bucket with an optional prefix.

        Returns:
            A list of dicts with ``Key``, ``Size``, and ``LastModified``.
        """
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=prefix
            )
            contents = response.get("Contents", [])
            return [
                {
                    "Key": obj["Key"],
                    "Size": obj["Size"],
                    "LastModified": obj["LastModified"],
                }
                for obj in contents
            ]
        except ClientError:
            logger.exception("Failed to list objects in s3://%s/%s", self.bucket_name, prefix)
            return []


def get_s3_client(config: Any) -> S3Client | None:
    """Create an S3Client from the app config, or ``None`` if S3 is disabled."""
    if not config.S3_ENABLED:
        logger.info("S3 is disabled — videos will not be uploaded")
        return None
    return S3Client(bucket_name=config.S3_BUCKET_NAME, region=config.AWS_REGION)
