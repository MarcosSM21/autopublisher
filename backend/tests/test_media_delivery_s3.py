"""S3-compatible provider with a stubbed client: no network (research.md §17)."""

from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from app.media_delivery import MediaDeliveryConfig, MediaDeliveryFailed
from app.media_delivery_s3 import S3CompatibleProvider
from tests.fakes import FAKE_DELIVERY_SECRET

CONFIG = MediaDeliveryConfig(
    provider="s3_compatible",
    endpoint_url="https://fake-account.r2.cloudflarestorage.com",
    bucket="autopublisher-temp",
    region="auto",
    access_key_id="FAKEACCESSKEY",
    secret_access_key=FAKE_DELIVERY_SECRET,
)


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=CONFIG.endpoint_url,
        region_name="auto",
        aws_access_key_id=CONFIG.access_key_id,
        aws_secret_access_key=CONFIG.secret_access_key,
    )


def test_put_sends_the_content_type_and_reports_progress() -> None:
    client = _client()
    provider = S3CompatibleProvider(CONFIG, client)
    progress: list[int] = []
    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": "autopublisher-temp",
                "Key": "autopublisher-tmp/a/b.jpg",
                "Body": stubber_any(),
                "ContentType": "image/jpeg",
                "ChecksumAlgorithm": stubber_any(),
            },
        )
        provider.put(
            "autopublisher-tmp/a/b.jpg", b"jpeg", "image/jpeg", 4, progress.append
        )
        stubber.assert_no_pending_responses()
    assert progress[-1] == 4


def test_signed_url_expires_and_is_hidden() -> None:
    provider = S3CompatibleProvider(CONFIG, _client())

    url = provider.signed_get_url("autopublisher-tmp/a/b.jpg", 900)

    revealed = url.reveal()
    assert revealed.startswith("https://fake-account.r2.cloudflarestorage.com/")
    assert "X-Amz-Expires=900" in revealed
    assert "X-Amz-Signature=" in revealed
    assert "X-Amz-Signature" not in repr(url)


def test_delete_is_idempotent() -> None:
    client = _client()
    provider = S3CompatibleProvider(CONFIG, client)
    with Stubber(client) as stubber:
        stubber.add_response("delete_object", {})
        stubber.add_client_error("delete_object", service_error_code="NoSuchKey")
        provider.delete("autopublisher-tmp/a/b.jpg")
        provider.delete("autopublisher-tmp/a/b.jpg")


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_errors_never_carry_details(operation: str) -> None:
    client = _client()
    provider = S3CompatibleProvider(CONFIG, client)
    with Stubber(client) as stubber:
        method = "put_object" if operation == "put" else "delete_object"
        stubber.add_client_error(
            method,
            service_error_code="AccessDenied",
            service_message=f"denied {FAKE_DELIVERY_SECRET}",
            http_status_code=403,
        )
        with pytest.raises(MediaDeliveryFailed) as raised:
            if operation == "put":
                provider.put("k", b"x", "image/jpeg", 1, lambda sent: None)
            else:
                provider.delete("k")
    assert str(raised.value) == ""
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def stubber_any() -> Any:
    from botocore.stub import ANY

    return ANY
