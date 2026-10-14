# Publishing to TikTok

A runbook for publishing **one local video** to a connected TikTok account with the
official **Content Posting API — Direct Post** and `source = FILE_UPLOAD`, with
**Publish now** or the generic scheduler. Connecting the account is described in
[tiktok-accounts.md](tiktok-accounts.md).

For a summary see the [Publishing to TikTok](../README.md#publishing-to-tiktok) section of
the README.

---

## Scope

- One video per publication (MP4, MOV or WebM), uploaded from the local file in chunks.
- Only the `video.publish` permission granted in Feature 012 is used.
- **Not supported**: photos and carousels, `PULL_FROM_URL`, domain verification, media
  delivery or R2, Upload to Draft / inbox, `video.upload`, `video.list`, listing posts,
  remote deletion, App Audit, transcoding, covers (`video_cover_timestamp_ms`), music,
  stickers or cross-posting.

## Unaudited client: private posts only

The TikTok app is a Sandbox / unaudited client (`CLIENT_AUDITED = False` in
`backend/app/tiktok_publishing.py`, deliberately not configurable):

- only the privacy **Only me** (`SELF_ONLY`) can be chosen; the other options TikTok
  returns are shown disabled with the reason;
- the destination TikTok account must be **private** when posting (*Settings → Privacy →
  Private account*). The review warns when Creator Info looks like a public account
  (`PUBLIC_TO_EVERYONE` offered); TikTok rejects the post otherwise
  (`tiktok_private_account_required`);
- TikTok's caps (active users per day, posts per creator) are dynamic: AutoPublisher never
  hard-codes them and only reports what TikTok answers.

**Product risk**: TikTok's Content Sharing Guidelines state that "A utility tool to help
upload contents to the account(s) you or your team manages" is not an acceptable intended
use for the audit. Public posting from AutoPublisher is therefore not guaranteed. This
does not block the current private use, and AutoPublisher does not try to work around
those rules.

## Review and options

The **TikTok** panel of a publication (TikTok's mandatory Direct Post UX):

1. **Creator Info** is read from TikTok every time the panel opens and with **Refresh**
   (never cached): nickname, avatar (display only; it expires after two hours), privacy
   options, interactions TikTok disabled and the maximum video duration. If TikTok says the
   creator cannot post now, publishing and scheduling are blocked.
2. **Preview** of the video and the **exact caption**: description, a blank line and the
   hashtags (the generic title is never sent). It is counted as TikTok does, in UTF-16
   code units (an emoji counts 2), up to 2200, and never shortened or rewritten.
3. **Who can view this video**: no default; choose **Only me**.
4. **Allow comments / duet / stitch**: unchecked by default (sent as
   `disable_* = true`); unchecked is valid. An interaction TikTok disabled for the account
   is shown disabled with the reason.
5. **Disclose commercial content**: off by default. When on, choose **Your brand**
   ("Promotional content") and/or **Branded content** ("Paid partnership"); with none
   chosen publishing is blocked ("You need to indicate if your content promotes yourself,
   a third party, or both."). Both toggles are always sent:

   | Choice | `brand_content_toggle` | `brand_organic_toggle` |
   |---|---|---|
   | Off | `false` | `false` |
   | Your brand | `false` | `true` |
   | Branded content | `true` | `false` |
   | Both | `true` | `true` |

   **Branded content** cannot be private: with **Only me** it is disabled ("Branded content
   visibility cannot be set to private."), so with the unaudited client it is never
   available.
6. **AI-generated: Yes / No**: no default; sent as `is_aigc`. Nothing is added to the
   caption.
7. **Declaration** with links to TikTok's official pages ("By posting, you agree to
   TikTok's Music Usage Confirmation.", or with Branded content "… Branded Content Policy
   and Music Usage Confirmation.") and its checkbox.

## Consent

Checking the declaration records a consent bound to a **fingerprint**: SHA-256 of the
TikTok account (`open_id`), the video digest (`Content.checksum`), the exact caption, every
option and the declaration version. Any material change (caption, privacy, interactions,
disclosure, AIGC, another file or another TikTok account) makes the consent **stale**;
the date and the generic title do not.

The panel says **"Consent recorded — matches saved publication metadata"** and **"File
integrity is rechecked before publishing."**: the consent only knows the stored digest.
Right before publishing the file is hashed again (streaming SHA-256) and compared; during
the upload the very bytes sent are hashed once more and the last chunk is only sent if
the digest still matches. A file that changed fails with `tiktok_video_changed` and the
panel shows that warning until a new consent is recorded.

**Publish now** always shows the current declaration again and requires its checkbox,
even with a consent already recorded; confirming records the consent again for the
fingerprint shown and only then starts the generic publication (`409
tiktok_consent_stale` stops it).

**Conscious limitation**: that explicit confirmation on every **Publish now** is enforced
by the dialog. The backend only checks that a consent for the current fingerprint exists;
a direct call to the generic publish API with a still-valid fingerprint has no extra
"recent consent" check. This is acceptable only for the current local single-user model
(no public API) and must be revisited for a multi-user system or a public API.

## Scheduling

Auto-publish (Feature 007) can only be enabled when the options are complete, the caption
is valid and the consent matches the current content; creating publications already armed
for a TikTok account is rejected for the whole batch (`409`, naming the TikTok
destination). At the scheduled time the scheduler runs the same preflight as **Publish
now**, Creator Info included.

If a material change is saved **after** arming, the publication stays scheduled and armed
but its consent becomes stale: at its time the local check blocks it with
`tiktok_consent_required` before any TikTok request, credential lookup, attempt or
upload. Confirming the declaration again within the automatic window is enough: the next
eligible automatic retry (currently every 120 s) publishes it without rescheduling. While
it stays stale inside the window, the scheduler logs a warning on every retry (expected).

## Upload and result

1. Preflight: local checks, the real file digest and a fresh Creator Info (privacy still
   offered, interactions still allowed, duration within the account's maximum).
2. `video/init/` is called **once** per attempt with the chunk plan: up to 64 000 000 B in
   one chunk; otherwise chunks of 32 MiB and a larger last chunk (at most 119 chunks for
   4 GB). The `publish_id` is saved before any byte is sent.
3. Intermediate chunks are read once from the original file and retried on the same
   buffer after a network error, timeout, 5xx or 429 (waits 2, 5 and 10 s). `400`/`404`
   fail, `403` means the upload URL expired. Chunks are sent with `Content-Range: bytes first-last/total`
   (inclusive last byte); TikTok answers `bytes 0-accepted/total`, where `accepted` is the
   number of bytes it holds (the next offset). A `416` on an intermediate chunk is only
   accepted when TikTok reports exactly `last + 1` bytes of the expected total (the chunk
   was already received); anything else fails before the last chunk. The upload must reach the last chunk within 50 minutes
   (the URL is valid one hour).
4. The last chunk is preceded by a **write-ahead** and sent **exactly once**. Whatever the
   answer (`201`, another HTTP status, a timeout or a lost answer), only the status of the
   same `publish_id` is read afterwards: after 3 s, then 3, 5, 5, 10, 10, 15, 15 s and every
   30 s, for at most 10 minutes. `PUBLISH_COMPLETE` is a success, `FAILED` a determined
   failure, and anything else stays **uncertain**.
5. Private posts usually complete without a public post ID: the publication is
   **Published** with no link (TikTok returns none for private posts). Open your TikTok
   profile to see the video; it may take a few minutes to appear.

`uploaded_bytes` (a byte count, seen while `PROCESSING_UPLOAD` and absent once complete)
is only kept for diagnosis and never decides anything.

## Uncertain results

An uncertain attempt is never retried automatically. Opening the publication (its publish
check) or **Publish now** first reads the status of the original `publish_id` (read-only):
`PUBLISH_COMPLETE` settles it as published, `FAILED` as not published; otherwise **Check
again** later, or check your TikTok profile and confirm that the video was not published
before publishing again. After a restart, attempts that had reached the last chunk are
uncertain; earlier ones are interrupted (nothing is resumed). Posts are never listed and
no second Direct Post is ever created to settle a doubt.

## Security

- Tokens are only used through Feature 012 (keyring); the `Authorization` header is never
  sent with chunks.
- The upload URL is an ephemeral secret: kept only in memory during the attempt, never
  stored, logged, returned by the API or shown in the browser; HTTP logs show
  `[redacted TikTok upload URL]`.
- The `publish_id` stays in the local database for diagnosis and is not exposed by the API.
- Nothing TikTok-related is stored in the browser.

## Errors (attempt codes)

| Code | Meaning |
|---|---|
| `tiktok_reconnect_required` | Credential or permission rejected; reconnect (Feature 012). |
| `tiktok_unavailable` / `tiktok_rate_limited` | Temporary problem before the last chunk; try again. |
| `tiktok_unexpected_response` | TikTok answered in an unexpected shape. |
| `tiktok_creator_cannot_post` | Daily limit, ban or app cap. |
| `tiktok_private_account_required` | The TikTok account must be private. |
| `tiktok_privacy_invalid` / `tiktok_init_failed` | TikTok rejected the post settings. |
| `tiktok_video_changed` | The file no longer matches the consented digest. |
| `tiktok_upload_failed` / `tiktok_upload_expired` | An intermediate chunk failed / the upload URL expired. |
| `tiktok_video_rejected` / `tiktok_content_rejected` / `tiktok_publish_failed` | TikTok answered `FAILED`. |
| `tiktok_processing_pending` / `tiktok_result_uncertain` | Uncertain: check again or check the profile. |

## Validation

Every real test publishes a private post: use harmless videos and **delete every test post
by hand** in the TikTok app (there is no remote deletion). The real checkpoints are in
[specs/013-tiktok-direct-post/quickstart.md](../specs/013-tiktok-direct-post/quickstart.md).
