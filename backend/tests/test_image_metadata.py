"""Image metadata removal (Feature 016, research §7).

One synthetic "dirty" file per format, generated here, carries every sentinel at
once (ComfyUI workflow/prompt, generation parameters, seed, models, LoRA, sampler,
a local path, a custom node key, GPS, device, dates) and Orientation 6. Pillow is
only the oracle that the image still looks the same."""

import io
import struct
import zlib
from collections.abc import Callable

import pytest
from PIL import Image, ImageCms, ImageOps

from app.image_metadata import (
    FRAME_KEEP,
    PNG_KEEP,
    WEBP_KEEP,
    _jpeg_keep,
    frame_chunks,
    jpeg_segments,
    png_chunks,
    read_ifd0,
    sanitize_image,
    webp_chunks,
)
from app.media import InvalidMediaError

SENTINELS = [
    b"SENTINEL_WORKFLOW",
    b"SENTINEL_PROMPT",
    b"KSampler",
    b"seed_987654321",
    b"sdxl_secret_checkpoint.safetensors",
    b"lora_secret_style.safetensors",
    b"euler_ancestral",
    b"/home/someone/ComfyUI/output",
    b"custom_node_secret_key",
    b"SENTINEL_DEVICE",
    b"SENTINEL_SOFTWARE",
    b"2026:01:02 03:04:05",
    b"SENTINEL_TRAILER",
    b"SENTINEL_XMP",
    b"SENTINEL_COMMENT",
]
WORKFLOW = (
    b'{"nodes":[{"type":"KSampler","widgets_values":["seed_987654321",'
    b'"euler_ancestral"]},{"type":"CheckpointLoader","ckpt":'
    b'"sdxl_secret_checkpoint.safetensors"},{"lora":'
    b'"lora_secret_style.safetensors","custom_node_secret_key":1}],'
    b'"path":"/home/someone/ComfyUI/output","id":"SENTINEL_WORKFLOW"}'
)
PROMPT = b'{"3":{"class_type":"KSampler","inputs":{"seed":"SENTINEL_PROMPT"}}}'
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _exif(orientation: int = 6, comfy: bool = False) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = (
        ("workflow:" + WORKFLOW.decode()) if comfy else "SENTINEL_DEVICE Make"
    )
    exif[0x0110] = ("prompt:" + PROMPT.decode()) if comfy else "SENTINEL_DEVICE"
    exif[0x0131] = "SENTINEL_SOFTWARE"
    exif[0x0132] = "2026:01:02 03:04:05"
    exif.get_ifd(0x8825)[1] = "N"
    exif.get_ifd(0x8825)[2] = (40.0, 26.0, 46.0)
    return exif


def _tiff(exif: Image.Exif) -> bytes:
    data = exif.tobytes()
    return data[6:] if data.startswith(b"Exif\x00\x00") else data


def _frames(mode: str) -> list[Image.Image]:
    return [
        Image.new(mode, (24, 16), color)
        for color in ((200, 30, 30, 120), (30, 200, 30, 255))
    ]


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def dirty_png() -> bytes:
    """An APNG with an ICC profile and metadata spread over every place."""
    buffer = io.BytesIO()
    first, *rest = _frames("RGBA")
    first.save(
        buffer, "PNG", save_all=True, append_images=rest, icc_profile=ICC, duration=100
    )
    data = buffer.getvalue()
    ihdr_end = 8 + 12 + 13
    extra = b"".join(
        [
            _png_chunk(b"tEXt", b"prompt\x00" + PROMPT),
            _png_chunk(b"tEXt", b"workflow\x00" + WORKFLOW),
            _png_chunk(b"zTXt", b"parameters\x00\x00" + zlib.compress(WORKFLOW)),
            _png_chunk(b"iTXt", b"extra_pnginfo\x00\x00\x00\x00\x00" + WORKFLOW),
            _png_chunk(b"tIME", b"\x07\xea\x01\x02\x03\x04\x05"),
            _png_chunk(b"eXIf", _tiff(_exif())),
            _png_chunk(b"comf", WORKFLOW),
            _png_chunk(b"prVt", b"/home/someone/ComfyUI/output"),
        ]
    )
    return data[:ihdr_end] + extra + data[ihdr_end:] + b"SENTINEL_TRAILER"


def _jpeg_segment(marker: int, data: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(data) + 2) + data


def dirty_jpeg() -> bytes:
    """A progressive JPEG with ICC, EXIF, XMP, IPTC, comments, JFXX, MPF and a
    trailer after EOI."""
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 60, 200)).save(
        buffer,
        "JPEG",
        progressive=True,
        icc_profile=ICC,
        exif=_exif(),
        comment=b"SENTINEL_COMMENT " + WORKFLOW,
        quality=90,
    )
    data = buffer.getvalue()
    extra = b"".join(
        [
            _jpeg_segment(
                0xE1,
                b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>SENTINEL_XMP</x:xmpmeta>",
            ),
            _jpeg_segment(0xED, b"Photoshop 3.0\x008BIM" + WORKFLOW),
            _jpeg_segment(0xE0, b"JFXX\x00\x10" + b"SENTINEL_TRAILER"),
            _jpeg_segment(0xE2, b"MPF\x00" + b"SENTINEL_DEVICE"),
            _jpeg_segment(0xFE, b"SENTINEL_COMMENT"),
        ]
    )
    return data[:2] + extra + data[2:] + b"SENTINEL_TRAILER" + WORKFLOW


def dirty_webp() -> bytes:
    """An extended, animated WebP with alpha, ICC, EXIF (ComfyUI style: the
    workflow in Make/Model) and XMP."""
    buffer = io.BytesIO()
    first, *rest = _frames("RGBA")
    first.save(
        buffer,
        "WEBP",
        save_all=True,
        append_images=rest,
        lossless=True,
        icc_profile=ICC,
        exif=_exif(comfy=True),
        xmp=b"<x:xmpmeta>SENTINEL_XMP SENTINEL_COMMENT</x:xmpmeta>",
        duration=100,
    )
    return buffer.getvalue() + b"SENTINEL_TRAILER"


def clean_file(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), (10, 20, 30)).save(buffer, fmt.upper())
    return buffer.getvalue()


DIRTY: dict[str, Callable[[], bytes]] = {
    "png": dirty_png,
    "jpeg": dirty_jpeg,
    "webp": dirty_webp,
}


def sanitize(data: bytes, fmt: str, **options: int) -> bytes:
    output = io.BytesIO()
    sanitize_image(io.BytesIO(data), output, fmt, **options)
    return output.getvalue()


def _blocks(data: bytes, fmt: str) -> list[tuple[bytes, bool]]:
    """(name, whitelisted) of every block of an image; the EXIF block is allowed
    here and its content is checked by `_exif_blocks`."""
    src = io.BytesIO(data)
    if fmt == "png":
        return [(c.type, c.type in PNG_KEEP | {b"eXIf"}) for c in png_chunks(src)]
    if fmt == "jpeg":
        return [
            (bytes([s.marker & 0xFF]), _jpeg_keep(s) or s.marker == 0xE1)
            for s in jpeg_segments(src)
        ]
    chunks, _ = webp_chunks(src)
    blocks = [(c.fourcc, c.fourcc in WEBP_KEEP | {b"EXIF"}) for c in chunks]
    for chunk in chunks:
        if chunk.fourcc == b"ANMF":
            blocks += [
                (c.fourcc, c.fourcc in FRAME_KEEP) for c in frame_chunks(src, chunk)
            ]
    return blocks


def _exif_blocks(data: bytes, fmt: str) -> list[dict[int, object]]:
    """IFD0 tags of every EXIF block left in the output."""
    src = io.BytesIO(data)
    found = []
    if fmt == "png":
        for c in png_chunks(src):
            if c.type == b"eXIf":
                ifd = read_ifd0(src, c.data_offset, c.data_length)
                assert ifd is not None
                found.append(ifd)
    elif fmt == "jpeg":
        for s in jpeg_segments(src):
            if s.marker == 0xE1:
                ifd = read_ifd0(src, s.offset + 10, s.length - 10)
                assert ifd is not None
                found.append(ifd)
    else:
        for c in webp_chunks(src)[0]:
            if c.fourcc == b"EXIF":
                ifd = read_ifd0(src, c.data_offset, c.data_length)
                assert ifd is not None
                found.append(ifd)
    return [{tag: ifd.short(tag) for tag in ifd.entries} for ifd in found]


def _appearance(data: bytes) -> list[tuple[str, tuple[int, int], bytes]]:
    image = Image.open(io.BytesIO(data))
    frames = []
    for index in range(getattr(image, "n_frames", 1)):
        image.seek(index)
        frame = ImageOps.exif_transpose(image.copy())
        frames.append((frame.mode, frame.size, frame.tobytes()))
    return frames


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
def test_dirty_image_is_sanitized(fmt: str) -> None:
    dirty = DIRTY[fmt]()
    # Each fixture carries nearly every sentinel in clear text.
    assert sum(sentinel in dirty for sentinel in SENTINELS) >= len(SENTINELS) - 2
    assert not all(kept for _, kept in _blocks(dirty, fmt))

    clean = sanitize(dirty, fmt)

    for sentinel in SENTINELS:
        assert sentinel not in clean, sentinel
    assert all(kept for _, kept in _blocks(clean, fmt))
    # The only EXIF left is the regenerated one-entry Orientation block.
    assert _exif_blocks(clean, fmt) == [{0x0112: 6}]
    # Same look: pixels, frames, alpha and ICC profile.
    assert _appearance(clean) == _appearance(dirty)
    assert Image.open(io.BytesIO(clean)).info.get("icc_profile") == ICC
    # Sanitizing the copy again finds nothing to remove.
    assert sanitize(clean, fmt) == clean


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
def test_clean_image_is_kept_byte_for_byte(fmt: str) -> None:
    data = clean_file(fmt)

    assert sanitize(data, fmt) == data


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
def test_truncated_image_is_rejected(fmt: str) -> None:
    dirty = DIRTY[fmt]()
    truncated = dirty[: len(dirty) // 2]

    with pytest.raises(InvalidMediaError):
        sanitize(truncated, fmt)


def test_jpeg_entropy_data_split_across_reads() -> None:
    dirty = dirty_jpeg()
    expected = sanitize(dirty, "jpeg")

    for read_size in (1, 2, 3, 7):
        assert sanitize(dirty, "jpeg", read_size=read_size) == expected
