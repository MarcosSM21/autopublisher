# Publishing to Threads

A runbook for publishing **text posts**, **single images** and **single videos** to a
connected Threads account through the official Threads API. The account must already be
connected (see [Connecting Threads accounts](threads-accounts.md)).

For a summary see the [Publishing to Threads](../README.md#publishing-to-threads) section
of the README.

---

## How it works

1. **Preflight**: nothing is uploaded or created yet. AutoPublisher checks the account,
   the credential, the permissions and the linked identity (`debug_token` and `/me`), the
   final text, the alt text, the media and the publishing limit Threads reports
   (`threads_publishing_limit`). Images and videos also need the temporary media delivery
   configured; text posts never use it.
2. **Temporary copy** (images and videos only): the file is uploaded to the same private
   S3-compatible bucket used for Instagram (see
   [docs/instagram-publishing.md](instagram-publishing.md#1-set-up-the-temporary-media-storage-once)).
   The random key is saved in SQLite before the upload starts. The signed URL is created
   only after the upload finished and travels only in the body of one request to Meta.
3. **Container**: AutoPublisher creates one media container (`TEXT`, `IMAGE` or `VIDEO`)
   and saves its id and creation time at once. Every `POST` to Threads sends its parameters
   (token, text, signed URL) in an `application/x-www-form-urlencoded` body, never in the
   request URL.
4. **Ready to publish**: the container status is read at once and then, only while Threads
   reports processing, after bounded waits:

   | Type | Waits between status reads | Maximum |
   |---|---|---|
   | Text | 2, 5, 10, 15 s, then every 15 s | 1 min |
   | Image | 2, 5, 10, 15 s, then every 30 s | 3 min |
   | Video | 10, 20, 30 s, then every 60 s | 5 min |

   A container is published only when it is **`FINISHED` and at least 30 seconds old**
   (`MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS`, counted from its saved creation time).
   `FINISHED` is necessary but not enough: in the real validation a text container read
   `FINISHED` about 300 ms after its creation was rejected by `threads_publish`, while an
   older one was accepted. Meta recommends waiting about 30 seconds on average; the 30 s
   minimum is AutoPublisher's conservative product policy, not a documented API minimum.
   A younger `FINISHED` container waits only the time it lacks (never a fixed extra
   30 s) and is read again before publishing, so a text post normally takes about 30 s.
   `ERROR`, `EXPIRED` and the timeout fail without publishing anything.
5. **Publish**: before `threads_publish`, AutoPublisher saves that it is about to publish
   (write-ahead). `threads_publish` is called **at most once per container** and never
   retried.
6. **Result**: the post ID is saved and the publication becomes **Published**. The
   official permalink is read afterwards as a best effort (see
   [Permalinks](#permalinks)).
7. **Cleanup** (images and videos): only after the result is saved, the temporary copy is
   deleted. A failed cleanup only adds a warning; the copy stays private and a later sweep
   deletes it.

**Publish now** and the shared scheduler (auto-publish at the scheduled time, pause,
concurrency) work as for YouTube and Instagram. Nothing Threads-specific runs in the
scheduler.

---

## 1. Text posts

Use **New text post** in the project's queue (shown when the project has an active Threads
account). A text post has no content from the library: its **text** and **hashtags** are
stored on the publication and edited from its details.

### Text composition

The text sent to Threads is exactly what the **Threads options** panel shows:

```text
<description>

#hashtag1 #hashtag2
```

The description of the publication (or of its content), a blank line and the hashtags as
`#a #b`. The title is **never** sent. AutoPublisher never trims, normalizes or shortens
the text; an invalid text is rejected before anything happens.

### Limits

- **500 characters**, counted conservatively: each character counts 1, except emoji, which
  count their UTF-8 bytes as Threads does (a code point outside the BMP counts 4; zero
  width joiners, variation selectors, keycaps and other symbols count their bytes). Some
  symbols may be over-counted; a text Threads would reject is never let through.
- **At most 5 unique links** (`http://`, `https://` or `www.`). Threads also rejects texts
  with more links at container creation (`THREADS_API__LINK_LIMIT_EXCEEDED`), reported as
  `threads_text_invalid`.
- A text post cannot be empty. Images and videos may have no text.

### What Threads does with the text

AutoPublisher sends the text exactly, but **Threads may transform it**:

- the **first link** may be shown as a link preview;
- the **first valid hashtag** may be turned into a **topic tag**. In the real validation
  AutoPublisher sent `…\n\n#autopublisher` and Threads stored the text as
  `…\n\nautopublisher` with `topic_tag = autopublisher`.

AutoPublisher never creates topic tags or link attachments itself and does not change how
the text is composed because of this.

---

## 2. Images

- **JPEG** and **PNG** are sent byte for byte.
- A **static WebP** is converted in memory to a **lossless PNG** (same size, EXIF
  orientation applied, transparency and ICC profile kept). The publish summary says
  `→ sent as PNG`. Nothing is written to disk; the original file is never modified.
- An **animated WebP** is rejected: AutoPublisher never picks a single frame.
- The checks apply to the file that is really sent (the derived PNG for WebP): at most
  **8 MB** (8 MiB) and an aspect ratio of at most **10:1**. Widths outside 320–1440 are
  accepted (Threads scales them). AutoPublisher never crops, pads, resizes or recompresses.
- **Alt text** (optional, up to 1000 characters) is set in the Threads options panel.

## 3. Videos

Videos are only checked, never transcoded. `ffprobe` is required: without it the preflight
fails (`threads_media_unverifiable`).

Checked locally, and failing when the value cannot be determined: MP4 or MOV container,
size ≤ 1 GB, a video stream, H.264 or HEVC, width ≤ 1920, aspect ratio 0.01:1 to 10:1,
duration > 0 and ≤ 300 s, 23–60 FPS, 4:2:0 chroma subsampling, `moov` atom at the start
(fast start) and, when there is audio, AAC, ≤ 48 kHz, mono or stereo.

Checked only when `ffprobe` reports them: video bitrate ≤ 100 Mbps (stream bitrate, else
the container's), audio bitrate ≤ 128 kbps and progressive scan.

**Delegated to Threads** (not verifiable robustly without analysing the bitstream): closed
GOP and edit lists, plus any of the three values above that `ffprobe` did not report.
Each attempt records them in `submitted.delegated_checks`; the interface never presents
them as validated. If Threads rejects the video for one of them, the container ends in
`ERROR` and nothing is published (`threads_media_rejected`).

**Alt text** is also available for videos.

### Signed URL lifetime

The signed URL is created after the upload and must outlive the container creation
(60 s) plus the longest processing wait (5 min for videos) plus a 5 min margin. The media
delivery configuration only accepts `url_ttl_seconds` ≥ 900, so no valid configuration
lets the URL expire while Threads may still fetch the media.

---

## 4. Publishing limit

AutoPublisher reads `threads_publishing_limit` (`quota_usage`, `config.quota_total`,
`config.quota_duration`; validated for real as
`{"data":[{"quota_usage":…,"config":{"quota_total":250,"quota_duration":86400}}]}`).

| Answer | Result |
|---|---|
| Understood, limit reached | The preflight fails: `threads_publishing_limit_reached`. |
| Temporary failure (network, 5xx, 429) | Publishing continues with the warning `quota_unavailable`; Threads itself rejects a post over the limit. |
| A shape AutoPublisher does not understand, or a 4xx | The preflight fails: `threads_unexpected_response`. This may mean Meta changed its contract (*contract drift*): review the gateway before publishing again. |

The quota is never used to decide whether an uncertain attempt published.

---

## 5. When something goes wrong

All messages are safe English texts; Meta's raw answers are never shown or stored.

| Code | Meaning |
|---|---|
| `threads_not_connected` / `threads_reconnect_required` / `threads_identity_mismatch` | Connect or reconnect the account (Feature 010). Credential or permission rejections during publishing also mark the account **Reconnect required**; temporary errors never change it. |
| `threads_text_invalid`, `threads_alt_text_invalid` | Fix the text or the alt text. |
| `threads_image_incompatible`, `threads_video_incompatible`, `threads_media_unverifiable` | The file does not meet the requirements, or cannot be inspected. |
| `media_delivery_not_configured`, `media_delivery_failed` | Temporary media storage (images and videos only). |
| `threads_container_failed` | Threads refused to prepare the post. |
| `threads_media_fetch_failed`, `threads_media_rejected`, `threads_processing_failed`, `threads_processing_timeout`, `threads_container_expired` | The container failed; nothing was published. |
| `threads_publish_failed` | Threads explicitly rejected the publication and the container is not published. |
| `threads_already_published` | A previous attempt of this publication was already published; nothing new was created. |
| `threads_publish_uncertain` | See below. |

### Uncertain results and reconciliation

If `threads_publish` gives no conclusive answer (timeout, connection cut, 5xx, 429, an
unexpected body), AutoPublisher **never calls it again and never creates another
container**. It only reads the status of the original container (after 0, 5, 15, 30 and
60 s):

- `PUBLISHED` → the publication is **Published** without a post ID or link, with the
  warning `remote_identity_unavailable` (the post is never searched for);
- anything else, or failing reads → the attempt stays **uncertain**
  (`threads_publish_uncertain`, manual review required). The message names the account,
  the UTC time and the start of the text, as help to find the post, never as proof.

When the publication is opened again (publish check or **Publish now**), AutoPublisher
reads that container once more (read-only). Only `PUBLISHED` settles it. Otherwise
publishing again requires confirming that you checked Threads. Before any new attempt,
the latest recent container of the publication is read once more: if Threads reports it
published, the attempt is blocked (`threads_already_published`).

A crash before the write-ahead closes the attempt as determined (nothing was published);
a crash after it leaves it uncertain and it is reconciled as above. Nothing is resumed
automatically.

---

## Permalinks

A post ID returned by `threads_publish` already determines the success. AutoPublisher then
reads the post (`GET /{post-id}?fields=id,permalink,timestamp`, with short retries of that
read only). If the permalink is missing (temporary failure, or omitted by Threads, e.g. for
copyright reasons) the publication stays **Published**, keeps the post ID, has no link and
shows `permalink_unavailable`. A link is never built from the ID or the username, and
**Open on Threads** appears only with an official permalink. A later light check may fill
in the permalink details.

---

## 6. What is not supported

Carousels, replies, polls, quote posts, explicit topic tags, link attachments, reply
controls, editing and deleting published posts. AutoPublisher has **no remote delete**:
delete test posts by hand in Threads.

## 7. Validated behaviour

The real validation (see `specs/011-threads-publisher/quickstart.md`) confirmed: form
bodies accepted for container creation and `threads_publish`; the quota shape above; a
text container `FINISHED` immediately but publishable only after the 30 s minimum age;
one `threads_publish`, the post ID and the permalink returned; no duplicate after a
restart; no secrets in SQLite, logs or API responses. Single images and videos (with alt
text, the signed temporary URL and its cleanup), a scheduled post, pause and resume were
validated as well.
