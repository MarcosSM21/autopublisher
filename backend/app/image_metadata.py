"""Metadata removal for PNG, JPEG and WebP images, without recompression.

Whitelist model (research §7): each format is walked block by block (PNG chunks,
JPEG segments and entropy-coded data, RIFF chunks) and only blocks needed to show
the image the same way are kept, copied byte for byte. Everything else (text
chunks with ComfyUI's `prompt`/`workflow`, EXIF, XMP, IPTC, comments, private
chunks, trailers…) is dropped. When the source declares an EXIF Orientation other
than 1, a minimal EXIF holding only that tag is written instead of the original
(FR-025a). A file with nothing to remove is reproduced byte for byte.

The source is processed in two passes over seekable files with bounded reads: a
plan (which byte ranges to copy, which few bytes to write) and its execution. No
file is ever loaded whole.
"""

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from app import config
from app.media import InvalidMediaError
from app.models import MediaFormat

# --- Plan ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Copy:
    """Copy `length` source bytes from `offset`; `png_crc` checks a PNG chunk."""

    offset: int
    length: int
    png_crc: bool = False


@dataclass(frozen=True)
class _Write:
    data: bytes


_Op = _Copy | _Write


def _invalid(message: str = "The image structure is not valid.") -> InvalidMediaError:
    return InvalidMediaError(message)


def _size_of(src: BinaryIO) -> int:
    src.seek(0, 2)
    return src.tell()


def _read_exact(src: BinaryIO, count: int) -> bytes:
    data = src.read(count)
    if len(data) != count:
        raise _invalid()
    return data


def _execute(src: BinaryIO, dst: BinaryIO, ops: list[_Op], read_size: int) -> None:
    for op in ops:
        if isinstance(op, _Write):
            dst.write(op.data)
            continue
        src.seek(op.offset)
        if op.png_crc:
            _copy_png_chunk(src, dst, op.length, read_size)
        else:
            _copy(src, dst, op.length, read_size)


def _copy(src: BinaryIO, dst: BinaryIO, length: int, read_size: int) -> int:
    """Copy `length` bytes, returning their CRC-32 (used for PNG)."""
    crc = 0
    remaining = length
    while remaining:
        data = src.read(min(read_size, remaining))
        if not data:
            raise _invalid()
        crc = zlib.crc32(data, crc)
        dst.write(data)
        remaining -= len(data)
    return crc


def _copy_png_chunk(src: BinaryIO, dst: BinaryIO, length: int, read_size: int) -> None:
    dst.write(_read_exact(src, 4))
    crc = _copy(src, dst, length - 8, read_size)
    stored = _read_exact(src, 4)
    if struct.unpack(">I", stored)[0] != crc:
        raise _invalid("The image is damaged (bad PNG checksum).")
    dst.write(stored)


# --- Minimal TIFF/EXIF reader ------------------------------------------------------

ORIENTATION_TAG = 0x0112
SHORT = 3
MAX_IFD_ENTRIES = 1024


@dataclass(frozen=True)
class IfdEntry:
    tag: int
    type: int
    count: int
    # The raw 4-byte value/offset field.
    value: bytes


@dataclass(frozen=True)
class Ifd0:
    little_endian: bool
    base: int
    length: int
    entries: dict[int, IfdEntry] = field(default_factory=dict)

    def short(self, tag: int) -> int | None:
        entry = self.entries.get(tag)
        if entry is None or entry.type != SHORT or entry.count != 1:
            return None
        value: int = struct.unpack(
            "<H" if self.little_endian else ">H", entry.value[:2]
        )[0]
        return value


def read_ifd0(src: BinaryIO, base: int, length: int) -> Ifd0 | None:
    """The entries of IFD0 of a TIFF block (EXIF), read with seeks; None when the
    block is not readable TIFF. Values stored elsewhere are not loaded."""
    if length < 8:
        return None
    src.seek(base)
    header = src.read(8)
    if header[:4] == b"II*\x00":
        little = True
    elif header[:4] == b"MM\x00*":
        little = False
    else:
        return None
    order = "<" if little else ">"
    offset: int = struct.unpack(order + "I", header[4:8])[0]
    if offset < 8 or offset + 2 > length:
        return None
    src.seek(base + offset)
    count_data = src.read(2)
    if len(count_data) != 2:
        return None
    count = min(
        struct.unpack(order + "H", count_data)[0],
        (length - offset - 2) // 12,
        MAX_IFD_ENTRIES,
    )
    entries: dict[int, IfdEntry] = {}
    for _ in range(count):
        raw = src.read(12)
        if len(raw) != 12:
            break
        tag, kind, number = struct.unpack(order + "HHI", raw[:8])
        entries.setdefault(tag, IfdEntry(tag, kind, number, raw[8:12]))
    return Ifd0(little, base, length, entries)


def exif_orientation(src: BinaryIO, base: int, length: int) -> int | None:
    """EXIF Orientation 2–8, or None (absent, 1 or unreadable: nothing to keep)."""
    ifd = read_ifd0(src, base, length)
    value = ifd.short(ORIENTATION_TAG) if ifd is not None else None
    return value if value is not None and 2 <= value <= 8 else None


def minimal_exif(orientation: int) -> bytes:
    """A regenerated TIFF block with a single IFD0 entry: Orientation (26 bytes)."""
    return (
        b"II*\x00"
        + struct.pack("<IH", 8, 1)
        + struct.pack("<HHIHH", ORIENTATION_TAG, SHORT, 1, orientation, 0)
        + struct.pack("<I", 0)
    )


# --- PNG ------------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_KEEP = frozenset(
    {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"cHRM",
        b"gAMA",
        b"iCCP",
        b"sRGB",
        b"sBIT",
        b"cICP",
        b"mDCV",
        b"cLLI",
        b"acTL",
        b"fcTL",
        b"fdAT",
    }
)


@dataclass(frozen=True)
class PngChunk:
    type: bytes
    # Offset of the length field; the chunk spans 12 + `data_length` bytes.
    offset: int
    data_length: int

    @property
    def data_offset(self) -> int:
        return self.offset + 8


def png_chunks(src: BinaryIO) -> Iterator[PngChunk]:
    """Every chunk up to IEND (anything after it is ignored)."""
    size = _size_of(src)
    src.seek(0)
    if src.read(8) != PNG_SIGNATURE:
        raise _invalid()
    position = 8
    while True:
        if position + 12 > size:
            raise _invalid()
        src.seek(position)
        length, kind = struct.unpack(">I4s", _read_exact(src, 8))
        if length > 0x7FFFFFFF or not kind.isalpha():
            raise _invalid()
        if position + 12 + length > size:
            raise _invalid()
        yield PngChunk(kind, position, length)
        position += 12 + length
        if kind == b"IEND":
            return


def _png_chunk_bytes(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data)
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _plan_png(src: BinaryIO) -> list[_Op]:
    chunks = list(png_chunks(src))
    if chunks[0].type != b"IHDR":
        raise _invalid()
    orientation = None
    for chunk in chunks:
        if chunk.type == b"eXIf":
            orientation = exif_orientation(src, chunk.data_offset, chunk.data_length)
            break
    ops: list[_Op] = [_Write(PNG_SIGNATURE)]
    exif_written = orientation is None
    for chunk in chunks:
        if chunk.type not in PNG_KEEP:
            continue
        if not exif_written and chunk.type in {b"IDAT", b"acTL", b"fcTL", b"IEND"}:
            # eXIf must precede the image data.
            assert orientation is not None
            ops.append(_Write(_png_chunk_bytes(b"eXIf", minimal_exif(orientation))))
            exif_written = True
        ops.append(_Copy(chunk.offset, 12 + chunk.data_length, png_crc=True))
    return ops


# --- JPEG -----------------------------------------------------------------------------

SOI, EOI, SOS, APP0, APP1, APP2, APP14, COM = (
    0xD8,
    0xD9,
    0xDA,
    0xE0,
    0xE1,
    0xE2,
    0xEE,
    0xFE,
)
# Entropy-coded data after an SOS segment (not a marker).
ECS = -1
RST = range(0xD0, 0xD8)
# DQT, DHT, DAC, DRI, DNL and the SOF markers (C0–CF without DHT/JPG/DAC).
JPEG_KEEP = frozenset(
    {0xDB, 0xC4, 0xCC, 0xDD, 0xDC, SOI, EOI, SOS, *RST}
    | {code for code in range(0xC0, 0xD0) if code not in {0xC4, 0xC8, 0xCC}}
)
JFIF_ID = b"JFIF\x00"
ICC_ID = b"ICC_PROFILE\x00"
ADOBE_ID = b"Adobe"
EXIF_ID = b"Exif\x00\x00"
IDENT_SIZE = 32


@dataclass(frozen=True)
class JpegSegment:
    marker: int
    # Offset of the 0xFF of the marker (of the data for ECS); `length` covers the
    # marker, its length field and its data.
    offset: int
    length: int
    # The first bytes of the data (APPn identifiers).
    ident: bytes = b""


def _scan_entropy(src: BinaryIO, start: int, read_size: int) -> int:
    """Offset of the 0xFF that starts the marker ending the entropy-coded data.
    `FF00` (stuffed byte), `RSTn` and `FF` fill bytes belong to the data; an `FF`
    split across two reads is carried over."""
    src.seek(start)
    position = start
    carry = b""
    while True:
        data = src.read(read_size)
        if not data:
            raise _invalid()
        buffer = carry + data
        buffer_start = position - len(carry)
        position += len(data)
        index = 0
        while True:
            found = buffer.find(b"\xff", index)
            if found == -1 or found + 1 >= len(buffer):
                break
            following = buffer[found + 1]
            if following == 0x00 or following in RST:
                index = found + 2
            elif following == 0xFF:
                index = found + 1
            else:
                return buffer_start + found
        carry = b"\xff" if found != -1 and found + 1 >= len(buffer) else b""


def jpeg_segments(
    src: BinaryIO, read_size: int = config.CHUNK_SIZE
) -> Iterator[JpegSegment]:
    """Every segment and entropy-coded block up to EOI (anything after it is
    ignored). Fill bytes between segments are skipped."""
    size = _size_of(src)
    src.seek(0)
    if src.read(2) != b"\xff\xd8":
        raise _invalid()
    yield JpegSegment(SOI, 0, 2)
    position = 2
    while True:
        src.seek(position)
        if src.read(1) != b"\xff":
            raise _invalid()
        code = _read_exact(src, 1)[0]
        while code == 0xFF:
            position += 1
            code = _read_exact(src, 1)[0]
        if code == EOI:
            yield JpegSegment(EOI, position, 2)
            return
        if code in RST or code == 0x01:
            yield JpegSegment(code, position, 2)
            position += 2
            continue
        if code == 0x00:
            raise _invalid()
        length = struct.unpack(">H", _read_exact(src, 2))[0]
        if length < 2 or position + 2 + length > size:
            raise _invalid()
        ident = src.read(min(IDENT_SIZE, length - 2))
        yield JpegSegment(code, position, 2 + length, ident)
        position += 2 + length
        if code == SOS:
            end = _scan_entropy(src, position, read_size)
            yield JpegSegment(ECS, position, end - position)
            position = end


def _jpeg_keep(segment: JpegSegment) -> bool:
    if segment.marker == ECS:
        return True
    if segment.marker == APP0:
        return segment.ident.startswith(JFIF_ID)
    if segment.marker == APP2:
        return segment.ident.startswith(ICC_ID)
    if segment.marker == APP14:
        return segment.ident.startswith(ADOBE_ID)
    return segment.marker in JPEG_KEEP


def _plan_jpeg(src: BinaryIO, read_size: int) -> list[_Op]:
    segments = list(jpeg_segments(src, read_size))
    orientation = None
    for segment in segments:
        if segment.marker == SOS:
            break
        if segment.marker == APP1 and segment.ident.startswith(EXIF_ID):
            header = 4 + len(EXIF_ID)
            orientation = exif_orientation(
                src, segment.offset + header, segment.length - header
            )
            break
    ops: list[_Op] = [_Copy(s.offset, s.length) for s in segments if _jpeg_keep(s)]
    # The minimal EXIF goes after SOI and, when it opens the file, APP0 JFIF.
    insert_at = 1
    if len(segments) > 1 and segments[1].marker == APP0 and _jpeg_keep(segments[1]):
        insert_at = 2
    if orientation is not None:
        tiff = minimal_exif(orientation)
        app1 = b"\xff\xe1" + struct.pack(">H", 2 + len(EXIF_ID) + len(tiff))
        ops.insert(insert_at, _Write(app1 + EXIF_ID + tiff))
    return ops


# --- WebP -----------------------------------------------------------------------------

WEBP_KEEP = frozenset({b"VP8X", b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L"})
FRAME_KEEP = frozenset({b"ALPH", b"VP8 ", b"VP8L"})
VP8X_EXIF = 0x08
VP8X_XMP = 0x04
ANMF_HEADER = 16


@dataclass(frozen=True)
class RiffChunk:
    fourcc: bytes
    # Offset of the FourCC; the chunk spans 8 + `data_length` (+ padding) bytes.
    offset: int
    data_length: int
    end: int

    @property
    def data_offset(self) -> int:
        return self.offset + 8


def _riff_chunks(src: BinaryIO, start: int, end: int) -> Iterator[RiffChunk]:
    position = start
    while position < end:
        if position + 8 > end:
            raise _invalid()
        src.seek(position)
        fourcc, length = struct.unpack("<4sI", _read_exact(src, 8))
        if position + 8 + length > end:
            raise _invalid()
        chunk_end = min(position + 8 + length + (length & 1), end)
        yield RiffChunk(fourcc, position, length, chunk_end)
        position = chunk_end


def webp_chunks(src: BinaryIO) -> tuple[list[RiffChunk], int]:
    """The top-level chunks and the end of the RIFF data (trailing bytes after it
    are ignored)."""
    size = _size_of(src)
    src.seek(0)
    header = src.read(12)
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WEBP":
        raise _invalid()
    riff_end = 8 + struct.unpack("<I", header[4:8])[0]
    if riff_end > size or riff_end < 12:
        raise _invalid()
    chunks = list(_riff_chunks(src, 12, riff_end))
    if not chunks:
        raise _invalid()
    return chunks, riff_end


def frame_chunks(src: BinaryIO, frame: RiffChunk) -> list[RiffChunk]:
    if frame.data_length < ANMF_HEADER:
        raise _invalid()
    start = frame.data_offset + ANMF_HEADER
    return list(_riff_chunks(src, start, frame.data_offset + frame.data_length))


def _chunk_size(chunk: RiffChunk) -> int:
    return chunk.end - chunk.offset


def _plan_webp(src: BinaryIO) -> list[_Op]:
    chunks, _ = webp_chunks(src)
    first = chunks[0]
    body: list[_Op] = []
    if first.fourcc in {b"VP8 ", b"VP8L"}:
        # Simple format: it cannot hold metadata; anything else is dropped.
        body.append(_Copy(first.offset, _chunk_size(first)))
    elif first.fourcc == b"VP8X" and first.data_length >= 10:
        src.seek(first.data_offset)
        flags = _read_exact(src, 1)[0]
        orientation = None
        for chunk in chunks:
            if chunk.fourcc == b"EXIF":
                base, length = chunk.data_offset, chunk.data_length
                src.seek(base)
                if src.read(len(EXIF_ID)) == EXIF_ID:
                    base, length = base + len(EXIF_ID), length - len(EXIF_ID)
                orientation = exif_orientation(src, base, length)
                break
        new_flags = flags & ~(VP8X_EXIF | VP8X_XMP)
        if orientation is not None:
            new_flags |= VP8X_EXIF
        body.append(_Copy(first.offset, 8))
        body.append(_Write(bytes([new_flags])))
        body.append(_Copy(first.data_offset + 1, _chunk_size(first) - 9))
        for chunk in chunks[1:]:
            if chunk.fourcc not in WEBP_KEEP or chunk.fourcc == b"VP8X":
                continue
            if chunk.fourcc == b"ANMF":
                body.extend(_plan_frame(src, chunk))
            else:
                body.append(_Copy(chunk.offset, _chunk_size(chunk)))
        if orientation is not None:
            tiff = minimal_exif(orientation)
            body.append(_Write(b"EXIF" + struct.pack("<I", len(tiff)) + tiff))
    else:
        raise _invalid()
    total = sum(op.length if isinstance(op, _Copy) else len(op.data) for op in body)
    return [_Write(b"RIFF" + struct.pack("<I", 4 + total) + b"WEBP"), *body]


def _plan_frame(src: BinaryIO, frame: RiffChunk) -> list[_Op]:
    """An ANMF frame keeping its header and its image chunks only."""
    kept = [c for c in frame_chunks(src, frame) if c.fourcc in FRAME_KEEP]
    length = ANMF_HEADER + sum(_chunk_size(c) for c in kept)
    ops: list[_Op] = [
        _Write(b"ANMF" + struct.pack("<I", length)),
        _Copy(frame.data_offset, ANMF_HEADER),
    ]
    # Sub-chunks keep their padding, so the frame length stays even.
    ops.extend(_Copy(c.offset, _chunk_size(c)) for c in kept)
    return ops


# --- Public API -----------------------------------------------------------------------


def sanitize_image(
    src: BinaryIO,
    dst: BinaryIO,
    fmt: MediaFormat | str,
    *,
    read_size: int = config.CHUNK_SIZE,
) -> None:
    """Write to `dst` the image of `src` without metadata (see module docstring).
    Raises `InvalidMediaError` when the structure is broken; `dst` may then hold a
    partial file that the caller discards."""
    media_format = MediaFormat(fmt)
    if media_format is MediaFormat.PNG:
        ops = _plan_png(src)
    elif media_format is MediaFormat.JPEG:
        ops = _plan_jpeg(src, read_size)
    elif media_format is MediaFormat.WEBP:
        ops = _plan_webp(src)
    else:
        raise ValueError(f"Not an image format: {media_format}")
    _execute(src, dst, ops, read_size)
