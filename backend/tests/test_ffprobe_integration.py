import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_project, import_one, make_mp4


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "L4i4")


@pytest.mark.real_ffprobe
@pytest.mark.skipif(
    shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
    reason="ffprobe/ffmpeg not installed",
)
def test_real_ffprobe_extracts_video_metadata(
    client: TestClient, project: dict[str, Any], tmp_path: Path
) -> None:
    video = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=10",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        timeout=60,
    )

    result = import_one(client, project["id"], "test.mp4", video.read_bytes())

    content = result["content"]
    assert result["status"] == "imported"
    assert (content["width"], content["height"]) == (64, 48)
    assert content["duration_seconds"] == pytest.approx(1, abs=0.2)


@pytest.mark.real_ffprobe
def test_video_imports_without_ffprobe(
    client: TestClient, project: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.media.shutil.which", lambda name: None)
    data = make_mp4(payload=b"no-ffprobe")

    result = import_one(client, project["id"], "clip.mp4", data)

    content = result["content"]
    assert result["status"] == "imported"
    assert content["media_type"] == "video"
    assert content["width"] is None
    assert content["height"] is None
    assert content["duration_seconds"] is None
    assert client.get(content["file_url"]).content == data
