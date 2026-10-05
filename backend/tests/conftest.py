import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import media
from app.main import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    return tmp_path / "media"


@pytest.fixture
def client(db_path: Path, media_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path, media_dir)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def stub_probe_video(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep tests independent of ffprobe unless they opt in with `real_ffprobe`."""
    if request.node.get_closest_marker("real_ffprobe") is None:
        monkeypatch.setattr(media, "probe_video", lambda path: media.VideoInfo())


def create_project(
    client: TestClient, name: str, description: str | None = None
) -> dict[str, Any]:
    response = client.post(
        "/api/projects", json={"name": name, "description": description}
    )
    assert response.status_code == 201, response.text
    project: dict[str, Any] = response.json()
    return project


def create_account(
    client: TestClient,
    project_id: int,
    platform: str,
    handle: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/accounts",
        json={"platform": platform, "handle": handle, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    account: dict[str, Any] = response.json()
    return account


_color_seed = 0


def make_image(
    fmt: str = "PNG",
    size: tuple[int, int] = (8, 6),
    color: tuple[int, int, int] | None = None,
) -> bytes:
    """Return a small valid image; each call without `color` yields different bytes."""
    global _color_seed
    if color is None:
        _color_seed += 1
        color = (_color_seed % 256, (_color_seed // 256) % 256, 128)
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def make_mp4(brand: bytes = b"isom", payload: bytes = b"") -> bytes:
    """Return a minimal ISO-BMFF file: an `ftyp` box and a `free` box."""
    ftyp = _box(b"ftyp", brand + b"\x00\x00\x02\x00" + brand + b"mp41")
    return ftyp + _box(b"free", payload or b"autopublisher")


def make_mov(payload: bytes = b"") -> bytes:
    return make_mp4(b"qt  ", payload)


def make_webm(payload: bytes = b"", doctype: bytes = b"webm") -> bytes:
    """Return a minimal EBML header with the given DocType."""
    body = b"\x42\x86\x81\x01" + b"\x42\x82" + bytes([0x80 | len(doctype)]) + doctype
    header = b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(body)]) + body
    return header + b"\xec" + bytes([0x80 | 0x20]) + (payload or b"x").ljust(32, b"\0")


def import_files(
    client: TestClient, project_id: int, files: list[tuple[str, bytes]]
) -> httpx.Response:
    return client.post(
        f"/api/projects/{project_id}/contents",
        files=[("files", (name, data)) for name, data in files],
    )


def import_one(
    client: TestClient, project_id: int, name: str, data: bytes
) -> dict[str, Any]:
    """Import a single file and return its result item."""
    response = import_files(client, project_id, [(name, data)])
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["results"][0]
    return result
