"""S3-compatible media delivery provider (Cloudflare R2 recommended; research.md §17).

The bucket stays private: objects are only readable through presigned GET URLs that
expire by themselves. botocore errors are never re-raised as they are, because their
messages may contain URLs or request details.
"""

import io
from typing import TYPE_CHECKING, Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.media_delivery import (
    PROVIDER_S3_COMPATIBLE,
    MediaDeliveryConfig,
    MediaDeliveryFailed,
    MediaSource,
    ProgressCallback,
    SecretUrl,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 60
# One thread: the progress callback writes to SQLite and must not run concurrently.
TRANSFER_CONFIG = TransferConfig(use_threads=False)


class S3CompatibleProvider:
    name = PROVIDER_S3_COMPATIBLE

    def __init__(self, config: MediaDeliveryConfig, client: Any = None) -> None:
        self.config = config
        self.client: S3Client = client or boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=READ_TIMEOUT_SECONDS,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def put(
        self,
        key: str,
        source: MediaSource,
        content_type: str,
        size: int,
        on_progress: ProgressCallback,
    ) -> None:
        sent = 0

        def callback(amount: int) -> None:
            nonlocal sent
            sent += amount
            on_progress(min(sent, size))

        try:
            if isinstance(source, bytes):
                self.client.upload_fileobj(
                    io.BytesIO(source),
                    self.config.bucket,
                    key,
                    ExtraArgs={"ContentType": content_type},
                    Callback=callback,
                    Config=TRANSFER_CONFIG,
                )
            else:
                with source.open("rb") as file:
                    self.client.upload_fileobj(
                        file,
                        self.config.bucket,
                        key,
                        ExtraArgs={"ContentType": content_type},
                        Callback=callback,
                        Config=TRANSFER_CONFIG,
                    )
        except (BotoCoreError, ClientError, OSError):
            raise MediaDeliveryFailed() from None
        on_progress(size)  # Confirmed by the provider.

    def signed_get_url(self, key: str, ttl_seconds: int) -> SecretUrl:
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.config.bucket, "Key": key},
                ExpiresIn=ttl_seconds,
            )
        except (BotoCoreError, ClientError):
            raise MediaDeliveryFailed() from None
        return SecretUrl(url)

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.config.bucket, Key=key)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404"}:
                return
            raise MediaDeliveryFailed() from None
        except BotoCoreError:
            raise MediaDeliveryFailed() from None
