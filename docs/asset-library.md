# Library and metadata cleaning

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
warn about the Drafts and scheduled Posts that would change.

## Search, filters and sort

They run in the browser over the Media the current view already loaded (All media, Unsorted
or one folder's own Media; never subfolders). There is no API for them.

- **Search** matches title, file name, caption (description) and hashtags. It ignores case
  and accents (`cafe` finds "Café"), drops a leading `#`, and every word must appear,
  each in any of those fields. Other characters are compared literally; there is no fuzzy
  matching.
- **Filters** combine (all must hold): **Type** (Images, Videos), **Usage** — *Used* is a
  Media with at least one Post that is not cancelled, in any state or account; *Unused* is
  every other Media — and **Imported** (last 7, 30 or 90 days, counted as 24-hour periods
  back from now).
- **Sort**: Newest (the API order), Oldest, Name A–Z and Name Z–A (title, else file name,
  in the browser's language, with `a2` before `a10`).
- **URL**: the state lives only in the view's URL (`q`, `type`, `usage`, `imported`,
  `sort`; defaults are omitted, unknown values ignored), so reload, back/forward and shared
  links restore it. Opening and closing a Media, Move, Delete and the way back from Publish
  ("Back to media", through a validated `from` parameter) keep it. Going to another folder
  starts a new view without it.
- **Selection**: changing the search or a filter empties the selection; sorting keeps it.
  Bulk Move and Delete only ever act on Media checked and visible when they were pressed.
- Active filters show as removable chips with **Clear all**. With no results, the view
  offers Clear search or Clear filters and, in a folder or Unsorted, **Search all media**
  (the same query over All media).
- On phones the filters live in a **Filters** sheet (applied at once) next to Sort.

## Folders

Each project's Library has its own folder tree (`library_folders`, up to 5 levels,
sibling names unique ignoring case and Unicode width). A Media has at most one folder
(`folder_id`, `null` = **Unsorted**); **All media** is every Media of the project.
Folders are logical only: creating, renaming, moving Media into them or deleting them
never touches a file on disk.

- `GET /api/projects/{id}/library-folders` returns the flat tree with each folder's direct
  `media_count`, plus `unsorted_count` and `total_count`.
- `GET /api/projects/{id}/contents?folder=<id>|unsorted` lists one view; without `folder`,
  All media. `POST …/contents?folder_id=<id>` imports into a folder.
- `POST /api/projects/{id}/contents/move` moves 1–500 Media in one transaction: all or
  nothing; another project's folder or Media answers `404`.
- Deleting a folder removes its subtree and moves its Media to Unsorted.

## Deleting

Every delete (Post, Media, Account, Project, folder) is a preview
(`GET …/{id}/deletion-preview`: counts, ready-to-show `summary`, `blocker` and an opaque
`confirmation` token of the scope) followed by `DELETE …/{id}?confirmation=<token>`. A
scope that changed meanwhile answers `409 deletion_changed` and nothing changes; a Post
being published (or metadata being removed) answers `409` with a plain message. The
token is not a permission: the routes stay behind the installation's sign-in. Deletes
never contact a platform. Media files and keyring logins are removed after the commit
through a cleanup queue (retried at start-up), only once nothing uses them.

## Clean metadata

**Clean metadata** (in the Media detail header) calls
`POST /api/contents/{id}/remove-metadata`, which sets the Media's metadata state:

| State | Meaning | File published |
|---|---|---|
| `unknown` | never cleaned | original |
| `clean` | checked: nothing had to be removed, no copy exists | original |
| `sanitized` | metadata removed into a clean copy | clean copy |

`ContentRead.publish_file.available` tells whether the file Posts would send (the
original for `clean`, the clean copy for `sanitized`) is on disk.

### Metadata badge

Every Media card, beside the usage indicator, and the Media detail header show one
badge derived in the frontend from those two fields only (no extra request, no polling):

| `metadata_status` | `publish_file.available` | Badge | Reason | Clean metadata offered |
|---|---|---|---|---|
| `unknown` | any | 🟡 Metadata not cleaned | Not cleaned yet | yes |
| `clean` | yes | 🟢 Metadata cleaned | Already clean | no |
| `clean` | no | 🟡 Metadata not cleaned | Media file missing | no |
| `sanitized` | yes | 🟢 Metadata cleaned | Cleaned copy | no |
| `sanitized` | no | 🟡 Metadata not cleaned | Clean copy missing | yes (recreates the copy) |

The badge answers "has AutoPublisher run its cleaning on this Media, and is the file it
publishes there?". It is not a forensic check of the file. A 🟡 Media can still be
published. The detail header is the only place with **Clean metadata**; the badge turns
green only after the backend has answered. **File details** keeps **Inspect metadata**,
the report and the checksums.

### Behaviour

- The original file is never opened for writing, moved or replaced.
- Before a cleaned file is accepted, the result is inspected again with the same
  inspector as **Inspect metadata**. If anything is still found, the clean is rejected
  with `422 metadata_not_removed`; if the result cannot be inspected, with
  `503 metadata_check_unavailable`. In both cases the temporary file is deleted and the
  state, the published file and the original stay as they were.
- Every publisher asks one resolver which file to send. For a `sanitized` Media it is
  always the clean copy: a missing copy (`media_unavailable`) or a copy whose SHA-256 no
  longer matches (`media_corrupt`, checked right before the upload) blocks publishing.
  There is no fallback to the original; running **Clean metadata** again recreates it.
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

In JPEG, a JFIF segment that carries a thumbnail (or extra data) is rebuilt with only
its version, units and density; a minimal JFIF is kept byte for byte, so an already clean
JPEG still ends `clean` without a copy. JFXX extension segments (thumbnails) are always
dropped. **Inspect metadata** reports a JFIF thumbnail as `other` / `JFIF thumbnail` and a
JFXX segment as `APP0:JFXX`.

When the original declares an EXIF orientation other than normal, the copy gets a new
EXIF block holding only that orientation, so the image is shown the same way.

### Videos

MP4, MOV and WebM keep their video and audio streams, copied without re-encoding (the
rotation is kept). Global and per-stream tags (such as the JSON comment written by
ComfyUI's Video Combine), chapters, cover images and data, subtitle and timecode
tracks are removed.

Cleaning a video needs `ffmpeg` to write the copy and `ffprobe` to check it. Both are
checked before ffmpeg runs: without `ffmpeg` the action fails with `ffmpeg_required`,
without `ffprobe` with `metadata_check_unavailable`. Importing and publishing work as
before. ExifTool is not a runtime dependency.

### Logs

No log line contains ffmpeg/ffprobe output (stderr or stdout), a traceback from them or
any metadata value: only the exception class name or the exit code.

## Accepted risks

- Ultra HDR / gain map images (MPF) lose their extra layer.
- Motion / Live Photo auxiliary data is dropped.
- Videos almost always get a copy, even when they were practically clean.
- Encoder strings inside the video bitstream (e.g. the H.264 encoder tag) and generic
  container values (`Lavf` without a version, generic handler names) can remain:
  removing them would require re-encoding, and they hold no workflow or user data.
- Copies cleaned before the post-clean check existed are not checked again and keep
  their green badge (they could still hold a JFIF thumbnail).
- A clean copy damaged without changing its size shows green until publishing, where
  the checksum check blocks it.
- Video inspection only sees what `ffprobe` exposes (container and stream tags).

## Future hardening (Feature 031, not implemented)

Deeper verification is left for a future Feature 031: persistent inspection evidence,
deep container parsers, re-checking existing copies (backfill), versioned inspection
rules, stream hashes and automatic inspection on import. None of this is implemented;
`specs/028-metadata-hygiene/reference-031/` is reference material for that feature, not
current behaviour.
