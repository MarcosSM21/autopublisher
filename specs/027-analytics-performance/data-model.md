# Data Model: Analytics & Performance (Feature 027)

Migration `0020_analytics_snapshots`. Two persistent tables for history plus one for refresh
state. Catalog, capabilities and engagement formulas live in code.

## Persistent entities

### `metric_snapshots` — one successful metrics read of one publication

| Field | Type | Rules |
|---|---|---|
| `id` | int PK | `sqlite_autoincrement` (NEVER_REUSE_IDS) |
| `publication_id` | FK → publications.id | indexed; deleted with the publication (`POST_DEPENDENTS`) |
| `platform` | str(20) | platform at capture time |
| `remote_id` | str(100) | the `external_id` used for the read (traceability) |
| `captured_at` | UTCDateTime | time AutoPublisher received the answer |
| `source` | str(60) | API call identifier, e.g. `youtube.videos.list:statistics`, `instagram.media:fields` |
| `trigger` | str(10) | `automatic` \| `manual` |

Index `(publication_id, captured_at)`. Only **successful** reads create a snapshot; failures
update only the refresh state.

### `metric_values` — one original metric inside a snapshot

| Field | Type | Rules |
|---|---|---|
| `snapshot_id` | FK → metric_snapshots.id | PK part; deleted with the snapshot |
| `metric_name` | str(60) | original platform name (`viewCount`, `like_count`…); PK part |
| `value` | int ≥ 0 | never NULL |
| `origin` | str(20) | `public_counter` \| `insight` |

A metric the adapter declares but the platform did not return has **no row**: that is
"not available", distinct from `value = 0` (FR-007). The common concept is not stored; it
comes from the catalog when reading, so a later mapping fix needs no data migration.

### `publication_metric_states` — refresh state per publication

| Field | Type | Rules |
|---|---|---|
| `publication_id` | PK, FK → publications.id | deleted with the publication |
| `status` | str(24) | see states below |
| `last_success_at` | UTCDateTime? | `captured_at` of the latest snapshot |
| `last_attempt_at` | UTCDateTime? | any trigger |
| `next_attempt_at` | UTCDateTime? | earliest automatic attempt |
| `manual_requested_at` | UTCDateTime? | accepted manual request not yet executed |
| `failure_count` | int | consecutive failures (backoff) |
| `error_code` | str(40)? | safe fixed code of the last failure (kept as detail, also while `pending`) |
| `error_message` | str(300)? | fixed, safe message (never tokens or raw bodies) |

A row is created when a manual request is accepted or on the first refresh attempt. A
refreshable publication with no row that is eligible for automatic refresh is shown as
`pending` (its first automatic read is accepted but not yet executed). One that is not eligible
(> 90 days and never requested) has no refresh state (`refresh: null`). There is no generic
`error` state: failure details live in `error_code`/`error_message`.

**Per-publication states** (`status`):

| State | Meaning | Automatic refresh |
|---|---|---|
| `pending` | refresh accepted (manual request or first automatic read) and not yet executed; it stays here while a platform pause or rate limit prevents running it | eligible (manual first) |
| `ok` | last attempt succeeded | at `next_attempt_at` = success + 24 h |
| `stale` | transient failure (network, 5xx, unknown); last data kept | backoff |
| `rate_limited` | the platform limited requests | at the platform's backoff end |
| `reconnect_required` | the connection is not usable | no, until the connection is `connected` again |
| `permission_required` | the account lacks the permission of every group of this adapter | no |
| `remote_not_found` | missing once | one retry ≥ 1 h later |
| `remote_deleted` | missing twice | no (a manual refresh is allowed) |

**Computed (not stored) per-publication display states**:

- `not_linked` (published without `external_id`; reason taken from the attempt's warning code
  or `details.tiktok_mode`);
- `not_supported`, `not_available_on_platform`, `not_applicable` (from the capability).

## Code-level entities

### Catalog (`analytics/catalog.py`)

Common concepts: `views`, `likes`, `comments`, `shares`. Each concept has a label, a definition
and `alignable: bool`. In v1 `likes` and `comments` are alignable; `views` and `shares` are
not. No concept is quantitatively comparable across platforms (FR-009).

### Adapter declaration (one per platform)

- `platform`;
- `metrics`: list of `{name, label, definition, origin, concept | None, group}`;
- `excluded`: officially deprecated/meaningless fields that are ignored, each with its reason
  (FR-006), e.g. YouTube `favoriteCount` (deprecated in 2015, always 0);
- `groups`: `{group_name: required_permission | None}`;
- `engagement`: `{numerator: [names], denominator: name} | None`;
- `batch_size`;
- `fetch(credentials, remote_ids) -> {remote_id: FetchResult}`.

| Platform | Group → permission | Metrics (v1 reads in **bold**) | Engagement |
|---|---|---|---|
| YouTube | `basic` → `youtube.readonly` (granted) | **viewCount**→views, **likeCount**→likes, **commentCount**→comments, **dislikeCount** (no concept) | (likeCount + commentCount) / viewCount |
| Instagram | `basic` → `instagram_business_basic` (granted); `insights` → `instagram_business_manage_insights` | **like_count**→likes, **comments_count**→comments; insights declared, not read | none in v1 |
| Threads | `insights` → `threads_manage_insights` | views, likes, replies→comments (note), reposts, quotes, shares — declared, not read | none in v1 |
| TikTok / Telegram / X | — | — | — |

The engagement formula is fixed per platform. It is computed at read time, never stored. It
is "not available" if any component is absent in that snapshot or the denominator is 0.

### Capability (computed per account, per group)

| Account state | Rule |
|---|---|
| `not_applicable` | X |
| `not_available_on_platform` | the platform offers no metrics (no platform in v1) |
| `not_supported` | TikTok in v1 (reason: no `video.list` scope and no public post ids); Telegram in v1 (its MTProto API offers metrics, but no adapter yet) |
| `not_connected` / `reconnect_required` | connection missing or not `connected` |
| `permission_required` | connected, but the group's permission is not granted (lists the missing group) |
| `supported` | connected and the group's permission is granted |

An account is refreshable when at least one group is `supported`. Instagram: `basic` is
supported and `insights` is `permission_required`; both appear in the UI.

## Refresh rules (unambiguous)

1. **Eligibility (common to both triggers)**: publication `published`; the succeeded attempt
   has `external_id`; the account has a refreshable capability.
2. **Automatic**: also `published_at ≥ now − 90 days`, status not in {`reconnect_required`,
   `permission_required`, `remote_deleted`}, and (`next_attempt_at` is NULL or ≤ now). After
   a success, `next_attempt_at = captured_at + 24 h`. So at most one automatic read per 24 h.
3. **Manual (one publication)**: allowed at any age and in any status except non-refreshable
   capability. Rejected with `409 refresh_cooldown` (with `available_at`) if
   `last_attempt_at > now − 15 min`; a rejected request is **not** queued. Otherwise it sets
   `manual_requested_at` and `status = pending` (keeping `last_success_at` and the error
   detail) and wakes the worker (`202`).
4. **Manual (project)**: enqueues every eligible publication of the project not in cooldown.
   Returns `{queued, in_cooldown, not_eligible}`.
5. **Order inside a tick**: manual requests (oldest first), then automatic ones (oldest
   `last_success_at` first, `pending` first). Grouped per account in batches of `batch_size`.
   At most 200 publications per tick.
6. **Publishing priority**: before each batch, if any attempt is `running` or any armed
   publication has `scheduled_at` within the next 10 minutes (or inside its overdue window),
   the tick stops. Manual requests stay queued. Publishing never waits for analytics.
7. **Errors → state and next attempt**:
   - success → `ok`, `failure_count = 0`;
   - transient → `stale`, next = now + min(1 h × 2^(failures−1), 24 h);
   - rate limit → `rate_limited`, platform paused (YouTube `quotaExceeded` on the general
     bucket: until next 00:00 America/Los_Angeles; others: 1 h, doubling up to 24 h); the
     rest of that platform's batches are skipped in this tick;
   - unauthorized / connection marked `reconnect_required` by `get_valid_credentials` →
     `reconnect_required`;
   - missing permission → `permission_required`;
   - remote id absent → `remote_not_found` (`error_code = remote_not_found`, next = now + 1 h),
     then a second absence ≥ 1 h after the first → `remote_deleted`. The previous absence is
     read from `error_code`, so it survives a manual request that set `pending` in between.

   An accepted request (`pending`) that cannot run because of a platform pause, a rate limit or
   publishing priority stays `pending` until it can run. A request inside the 15-minute
   cooldown is rejected with `409` and never queued.
8. **YouTube budget**: at most 200 units per Pacific day of the **general** quota bucket
   (in-memory counter; `videos.list` = 1 unit per batch). It does not touch the separate
   `videos.insert` bucket; it keeps room in the general bucket for the auxiliary
   publishing/connection calls (`channels.list`, post-upload `videos.list` status). Once
   reached, YouTube analytics waits until the reset.
9. The automation pause (`AutomationSettings`) does **not** affect analytics (FR-017).
   Analytics never writes to `publications` or `publication_attempts`.
