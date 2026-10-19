# Library and metadata removal

The media of a project are presented as the **Library** (each item is a **Media**).
Internally the model and the API keep the name `Content`; nothing was renamed.

## Usage

Usage is derived from the publications each time it is read (aggregate queries per
project), never stored, and it never changes data or calls a platform:

| Publication status | Counts as used | Shown as |
|---|---|---|
| `published` | yes | platform name |
| `awaiting_user_action` (TikTok inbox) | yes, but not as published | platform + `Ready in TikTok` |
| `scheduled` | no | `Scheduled` |
| `unscheduled`, `publishing`, `failed`, `cancelled` | no | — |

So Library cards can be drawn without loading every Post, each Media's usage summary
also carries counts by visible state (`post_display_state`, the same meaning the Posts
screen shows): `draft_count`, `attention_count` (Failed, Needs review, Needs action and
Missed), `upcoming_count`, `cancelled_count` and `next_scheduled_at`. A card shows one
indicator: what needs attention first, then the next scheduled time, Drafts, Published
or **Not used yet**.

`GET /api/contents/{id}/usage` returns the Media's Posts for the **Usage** section of
Media detail. Each row includes its `display_state` computed by the backend and, per
text field, whether it still follows the Media (`inherits`), so editing the Media can
warn about the Drafts and scheduled Posts that would change. Search and filters (`All`,
`Images`, `Videos`, `Not used yet`) run in the browser on the loaded Library.

## Remove metadata

`POST /api/contents/{id}/remove-metadata` sets the Media's metadata state:

| State | Meaning | File published |
|---|---|---|
| `unknown` | never checked | original |
| `clean` | checked: nothing had to be removed, no copy exists | original |
| `sanitized` | metadata removed into a clean copy | clean copy |

- The original file is never opened for writing, moved or replaced.
- Every publisher asks one resolver which file to send. For a `sanitized` Media it is
  always the clean copy: a missing copy (`media_unavailable`) or a copy whose SHA-256 no
  longer matches (`media_corrupt`, checked right before the upload) blocks publishing.
  There is no fallback to the original; running **Remove metadata** again recreates it.
- The action is rejected while a Post of the Media is publishing, and a
  Post cannot start while its Media is being sanitized. A publication prepared
  just before the copy was created is rejected (`content_file_changed`) and can be
  published again; TikTok asks to confirm the consent again because the file changed.
- Clean copies left behind by a crash are deleted at start-up. Importing a file
  identical to a clean copy of the same project is reported as a duplicate.
- `GET /api/contents/{id}/metadata` lists the categories found in the original and in
  the clean copy (location, device, software, dates, EXIF, XMP, IPTC, comments,
  container tags, AI generation, ComfyUI, other) with key names only, never values.

### Images

PNG, JPEG and WebP are rewritten by keeping a whitelist of blocks, copied byte for byte
(no recompression): image data, animation frames, transparency and color/HDR
information. Everything else is dropped, including:

- ComfyUI `workflow` and `prompt` text chunks and the `comf` chunk (PNG), and the
  workflow ComfyUI stores in the EXIF of animated WebP;
- `parameters`, `extra_pnginfo` and other generation fields;
- EXIF (GPS, device, dates, software), XMP, IPTC, comments, thumbnails, private chunks
  and any data after the end of the image.

When the original declares an EXIF orientation other than normal, the copy gets a new
EXIF block holding only that orientation, so the image is shown the same way.

### Videos

MP4, MOV and WebM keep their video and audio streams, copied without re-encoding (the
rotation is kept). Global and per-stream tags (such as the JSON comment written by
ComfyUI's Video Combine), chapters, cover images and data, subtitle and timecode
tracks are removed.

`ffmpeg` is only needed for this action. Without it, removing metadata from a video
fails with `ffmpeg_required`; importing and publishing work as before. ExifTool is not a
runtime dependency.

## Accepted risks

- Ultra HDR / gain map images (MPF) lose their extra layer.
- Motion / Live Photo auxiliary data is dropped.
- Videos almost always get a copy, even when they were practically clean.
- Encoder strings inside the video bitstream (e.g. the H.264 encoder tag) and generic
  container values (`Lavf` without a version, generic handler names) can remain:
  removing them would require re-encoding, and they hold no workflow or user data.
