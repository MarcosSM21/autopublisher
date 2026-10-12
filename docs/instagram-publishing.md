# Publishing to Instagram

A runbook for publishing **single images** (feed posts) and **single videos as Reels** to a
connected Instagram Professional account. The account must already be connected (see
[Connecting Instagram accounts](instagram-accounts.md)).

For a summary see the [Publishing to Instagram](../README.md#publishing-to-instagram)
section of the README.

---

## How it works

With Instagram Login, Meta does not accept a file upload: it **downloads the media from a
public HTTPS URL** while it prepares the post. AutoPublisher stays local, so for each
publication it makes a short-lived, private copy of the file available to Meta:

1. **Preflight** — nothing is uploaded or created yet. AutoPublisher checks the account,
   the credential, the identity, the caption, the options, the media and Instagram's own
   publishing limit (`content_publishing_limit`, Meta's number is the only source of
   truth).
2. **Temporary copy** — the file is uploaded to a **private** bucket under a random key.
   The key is saved in SQLite *before* the upload starts, so it can always be found and
   deleted later. Meta receives a **signed URL that expires by itself** (1 hour by
   default).
3. **Container** — Instagram prepares the post from that URL. AutoPublisher reads its
   status with bounded waits (2, 5, 10, 20, 30 s, then every 60 s; at most 5 minutes for
   images and 10 minutes for Reels).
4. **Publish** — `media_publish` is called **exactly once**. Before calling it,
   AutoPublisher saves that it is about to publish, so a crash at that moment is never
   mistaken for "nothing happened".
5. **Result** — the media ID and the permalink are saved and the publication becomes
   **Published** with an **Open on Instagram** link.
6. **Cleanup** — only after the result is saved, the temporary copy is deleted. If that
   fails, the publication stays **Published** and shows a warning; the copy stays private
   and is deleted by a later sweep.

The scheduler is the same as for YouTube: an Instagram publication can be published with
**Publish now** or automatically at its scheduled time when auto-publish is enabled.

---

## 1. Set up the temporary media storage (once)

AutoPublisher supports any **S3-compatible** storage with presigned URLs. Cloudflare R2
is recommended (free tier: 10 GB-month, no egress fees). These steps use R2.

### 1.1 Private bucket

1. Cloudflare dashboard → **R2** → **Create bucket**, e.g. `autopublisher-temp`.
2. Keep it **private**: do not enable public access, a custom domain or the `r2.dev`
   subdomain. Objects are only readable through signed URLs.
3. A dedicated bucket is recommended. If you share a bucket, AutoPublisher only ever
   writes under its own prefix (`autopublisher-tmp/` by default).

### 1.2 Lifecycle rule — mandatory

A safety net that deletes any private orphaned object that survives every cleanup of
AutoPublisher (for example after a crash and a failed sweep). It **does not** replace the
immediate cleanup and **does not** control when the signed URL stops working (the URL
expires by itself).

In the bucket → **Settings** → **Object lifecycle rules** → **Add rule**:

- Name: `autopublisher-temporary-media`.
- Prefix: **exactly** `autopublisher-tmp/` (the same value as `key_prefix` below). Never
  apply it to the whole bucket.
- Action: **Delete objects** after **1 day**.
- If offered: abort incomplete multipart uploads after 1 day.

R2 removes expired objects *typically within 24 hours*, so an orphaned object lives at
most about **48 hours**. Equivalent rule through the S3 API (with admin credentials, not
AutoPublisher's):

```json
{"Rules": [{"ID": "autopublisher-temporary-media", "Status": "Enabled",
  "Filter": {"Prefix": "autopublisher-tmp/"},
  "Expiration": {"Days": 1},
  "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}]}
```

AutoPublisher cannot check this rule itself (its token cannot read bucket settings), so
make sure it shows as **Enabled**.

### 1.3 Scoped API token

R2 → **Manage API tokens** → **Create API token** with **Object Read & Write** limited to
that bucket only. Note the **Access Key ID**, the **Secret Access Key** and the S3
endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

### 1.4 Local configuration

Create `backend/data/media-delivery.json` (or point `AUTOPUBLISHER_MEDIA_DELIVERY_FILE`
to another path):

```json
{
  "provider": "s3_compatible",
  "endpoint_url": "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
  "bucket": "<bucket>",
  "region": "auto",
  "access_key_id": "<access key id>",
  "secret_access_key": "<secret access key>",
  "key_prefix": "autopublisher-tmp/",
  "url_ttl_seconds": 3600
}
```

- `endpoint_url` must be `https`; `key_prefix` must end with `/` (a dedicated folder);
  `url_ttl_seconds` must be between 900 and 86400.
- **Never commit it.** `backend/data/` and `media-delivery*.json` are git-ignored. The
  file is read on every use (no restart needed) and is never sent to the browser.
- Moving the secret access key to the system keyring is possible future hardening; for
  now it follows the same local-file model as the Meta App secret.

Until this file is valid, Instagram publications show
**media_delivery_not_configured** and nothing is published.

### What is and is not supported

- The bucket stays **private**; temporary access only happens through the signed,
  expiring URL, which is treated as a secret (never stored in SQLite, logged or shown).
- AutoPublisher never creates or keeps a **permanent public copy** of your media.
- Anonymous **Quick Tunnels** (and similar development tools) are **not** a supported
  production solution.

---

## 2. Publish

1. Import the image or video, set its description and hashtags, and create a publication
   for the connected Instagram account.
2. Open it in the **Queue**. The **Instagram options** panel shows:
   - the post type: **Image Post** (images) or **Reel** (videos);
   - the **exact caption** that will be sent: the description, a blank line and the
     hashtags (`#a #b`). The title is not sent. Instagram's limits are 2200 characters,
     30 hashtags and 20 mentions; AutoPublisher never truncates, it reports the problem;
   - **AI-generated content** (Yes/No): must be declared explicitly; it is sent as
     Instagram's `is_ai_generated` self-disclosure. AutoPublisher never guesses it;
   - **Share to feed** (Reels only, on by default): the Reel appears in the feed and in the
     Reels tab; off shows it only in the Reels tab. It is always sent explicitly;
   - **Alt text** (images only, optional, at most 1000 characters); never generated;
   - any problem with the media, the caption or the configuration.
3. Click **Publish now** and confirm. The progress shows *Uploading N %* (the real upload
   of the temporary copy), then *Processing on Instagram* and *Publishing on Instagram*
   without invented percentages. 100 % only appears once the post is published.

### Media requirements

Checked before anything is uploaded; files are never modified.

- **Images** — sent as JPEG, at most 8 MB, aspect ratio between **4:5 and 1.91:1**.
  JPEG files are sent byte for byte. Static PNG and WebP images are converted to JPEG in
  memory (orientation applied, colour profile kept, no resizing or cropping). Images
  with transparent areas, animations, CMYK JPEG files or ratios outside the range are
  rejected with an explanation: AutoPublisher never crops, pads or flattens them.
- **Reels** — MP4 or MOV with the index at the start ("fast start"), H.264 or HEVC,
  progressive, 4:2:0, 23–60 FPS, at most 1920 px wide, aspect ratio 0.01:1–10:1, at most
  25 Mbps, 3 s to 15 min, at most 300 MB; audio, if any, AAC, at most 48 kHz, mono or
  stereo. `ffprobe` must be installed to check them; videos are never transcoded.

---

## 3. When something goes wrong

- Every failure has a fixed message and code (for example
  `instagram_container_failed`, `instagram_media_fetch_failed`,
  `instagram_processing_failed`, `instagram_processing_timeout`,
  `instagram_publishing_limit_reached`, `media_delivery_failed`). Meta's raw answers,
  tokens and signed URLs are never shown, stored or logged.
- If Instagram rejects the credentials, the account becomes **Reconnect required**.
  Temporary network or Meta problems never do.
- A **failed** publication can be fixed and published again; that creates a new attempt.
  A container that is still ready for exactly the same content is reused instead of
  creating another one. If the previous container already shows as published, Instagram
  refuses a new attempt (`instagram_already_published`).

### Uncertain results

If `media_publish` gets no clear answer (timeout, lost connection, AutoPublisher stopping
at that moment), AutoPublisher **never calls it again**. It only reads the status of the
original container:

- **Published** → the publication becomes **Published**. Meta offers no official way to
  get the post ID from the container, so there is no **Open on Instagram** link: the
  warning *Instagram confirmed the post was published but did not return its ID* tells
  you to open your profile. AutoPublisher never guesses the post from recent posts.
- **Anything else** (including *error* or *expired*) → the outcome stays **uncertain**.
  The publication shows *Check Instagram* with the account, caption and time of the
  attempt. Look for the post on your profile; publishing again requires confirming that
  it was not published.

When you open an uncertain publication later (or click **Publish now**), AutoPublisher
reads the original container once more: if Instagram now confirms it as published, the
publication becomes **Published** without asking anything. The time shown is
approximate (when AutoPublisher started the final step). There is no background polling.

---

## 4. Validated behaviour

Validated against Instagram and Cloudflare R2 on 2026-10-12 with an own Professional
account (tester of an own Meta App, Standard Access):

- Meta accepts the presigned R2 GET URL; the account ID from Instagram Login works for
  publishing.
- Single images, Reels and scheduled publications were published once each; the
  temporary copies were deleted after **Published** and nothing repeated after a restart.
- `content_publishing_limit` returned `quota_total = 100` per 86400 s. `quota_usage` may
  update with a delay, so it is not an immediate counter; AutoPublisher only uses it to
  stop when Meta reports the limit as reached.
- Observed times (not guarantees): an image took about 10 s from **Publish now** to
  **Published**; a short Reel about 45 s, most of it Instagram's processing.

## 5. App Review and test posts

- Publishing to your own account, added as an **Instagram tester** of your own Meta App,
  works with Standard Access. Publishing for accounts of other people needs Advanced
  Access, App Review and Business Verification, which AutoPublisher does not try to work
  around.
- Instagram has no private posts: **every test publishes for real**. Use harmless content
  made for the test and delete test posts by hand in the Instagram app — AutoPublisher
  does not edit or delete remote posts.
