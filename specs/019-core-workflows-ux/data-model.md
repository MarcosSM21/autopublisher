# Data Model — Feature 019

**No new tables, columns, migrations or persisted entities.** Feature 019 changes only:
(1) two read-model schemas (additive fields), (2) one lifecycle transition reachable through
the existing `PATCH /publications/{id}`. Everything else is client state.

## 1. `ContentUsageRead` (extended, additive)

Computed in `asset_library.usage_by_content` (still per project, now 3 queries instead of 2).

| Field | Type | New | Meaning |
|---|---|---|---|
| `used`, `publication_count`, `published_count`, `awaiting_count`, `scheduled_count`, `platforms`, `last_published_at` | — | no | Unchanged (Feature 016). |
| `draft_count` | int | yes | Posts whose display state is `draft`. |
| `attention_count` | int | yes | Posts whose display state is `failed`, `needs_review`, `needs_action` or `missed`. |
| `upcoming_count` | int | yes | Posts in `publishing`, `scheduled_automatic`, `scheduled_manual`, `scheduled_paused`. |
| `next_scheduled_at` | datetime \| null | yes | Earliest `scheduled_at` among `scheduled_*` display states. |
| `cancelled_count` | int | yes | Cancelled posts ("Not used yet" ⇔ `publication_count == cancelled_count`). |

Rules:
- Display state comes **only** from `post_state.post_display_state` with the same `now` and
  `paused` for the whole response; `latest_attempt` is passed only where it changes the
  result category (it never does for counts: `failed` and `needs_review` both count as
  attention).
- Card indicator (frontend, by priority): `attention_count>0` → "N need attention";
  `upcoming_count>0` → "Scheduled · <next_scheduled_at>" (or "Publishing"); `draft_count>0`
  → "N drafts"; `published_count>0` → "Published"; `publication_count==cancelled_count` →
  "Not used yet".

## 2. `AssetPublicationRead` (extended, additive)

Returned by `GET /contents/{id}/usage`.

| Field | Type | New | Meaning |
|---|---|---|---|
| existing fields | — | no | Unchanged (`status`, `uncertain` kept for compatibility). |
| `display_state` | PostDisplayState | yes | From `post_display_state` (needs latest attempt, already loaded). |
| `inherits` | `{title: bool, description: bool, hashtags: bool}` | yes | `true` when the override is `null` (the field follows the Media). |
| `consent_covers_caption` | bool | yes | TikTok, mode Direct Post, consent recorded (`consent_fingerprint` not null). Editing an inherited caption field would make that consent stale. One query on `tiktok_publication_options` for the TikTok rows. No fingerprint recomputation, no file hashing, no network. |

## 3. Publication lifecycle — one refined transition (R6)

Existing transitions unchanged, including Reactivate (004/007). Added:

| From | Trigger (`PATCH /publications/{id}`) | To | Conditions |
|---|---|---|---|
| `FAILED` | body contains `scheduled_at` (non-null, future) [+ `auto_publish_enabled: true`] | `SCHEDULED` | `requires_remote_check` is false; `ensure_future`; `ensure_can_prepare`; if arming: `_set_consent` + `arming_problems` (TikTok consent valid). |
| `FAILED` | body contains `scheduled_at: null` | `UNSCHEDULED` (Draft) | `requires_remote_check` is false. |

Effects of both: `disarm()` first (then arm if requested), `auto_publish_error` cleared,
attempts untouched (history preserved), `updated_at` set. For `FAILED` the presence of the
field triggers the transition even when the value equals the current one (a failed Publish
now has `scheduled_at = null`), and the same presence counts as a scheduling change for the
`check_result_first` guard (so `{scheduled_at: null}` on an uncertain Failed is rejected).

Rejection: `409 check_result_first` — "Check the result first." (field
`scheduled_at`) whenever the latest attempt of the content+account pair is uncertain
(`requires_remote_check`, the same rule the scheduler and Publish now already use).

`FAILED` + overrides-only edits keep their current behaviour.

## 4. Client-side models (not persisted)

### Publish set
- Identity: ordered, deduplicated list of Post ids in `?posts=`.
- Mode: `media` (route `/p/:pid/library/:mid/publish`) or `text` (`/p/:pid/posts/new`).
- Membership validation per id: exists, `project_id == pid`, and `content_id == mid`
  (media) or `content_id == null` (text). Invalid ids are dropped (`replace` navigation)
  with an inline notice "N posts couldn't be included".
- Each member is partitioned by its backend `display_state`: `draft` → Review part; any
  other → Result part.

### Compose draft (React state only, until Continue)
```text
selected: accountId[]            # order = destination list order
presetNotice: {skipped: {accountId, reason}[]} | null
common: { description: string, hashtags: string[] }   # prefilled from Media
custom: Record<accountId, Partial<{title, description, hashtags}>>  # dirty fields only
```
Snapshot at Continue (per selected account): `description_override = custom.description ??
common.description`, `hashtags_override = custom.hashtags ?? common.hashtags`,
`title_override = custom.title ?? media.title ?? ""` only for title platforms (YouTube).
Empty values are explicit (`""`, `[]`). Sent as `targets[accountId]` with no common fields
(see contracts/api.md §1).

### TikTok declaration (per action)
`accepted: { fingerprint, version } | null`; valid iff equal to current options'
`fingerprint` and `declaration.version`. Never persisted until the final CTA calls
`tiktok-consent`.

### Autosave entry (per platform card)
`status: idle | saving | saved | error`, `pending: T | null`, `inFlight: boolean`;
registered in the task's `AutosaveRegistry` (`flushAll(): Promise<boolean>`).
