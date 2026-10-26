# API contract — Feature 024

No new endpoints. One existing endpoint gains a concurrency guarantee; its request, response
and error contract do not change.

## `PATCH /api/publications/{id}` (unchanged shape)

**Request** (`PublicationUpdate`; omitted fields keep their value):

```json
{
  "scheduled_at": "2026-10-30T17:30:00Z",
  "auto_publish_enabled": true,
  "title_override": "…",
  "description_override": "…",
  "hashtags_override": ["…"]
}
```

Reschedule from Calendar (Quick Reschedule or drop) always sends exactly
`{ "scheduled_at": <future ISO instant>, "auto_publish_enabled": true }`, like
`ActionDialog` today. A TikTok Direct Post records its declaration first through the existing
`POST /api/publications/{id}/tiktok-consent`.

**Response**: `200` with `PublicationRead` (unchanged).

**Errors** (unchanged codes and bodies):

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | Unknown publication |
| 409 | `publication_cancelled` | Cancelled |
| 409 | `publication_not_editable` | `publishing`, `published`, `awaiting_user_action` — **including when the scheduler claimed it concurrently** |
| 409 | `check_result_first` | Failed with an uncertain last attempt (`needs_review`) |
| 409 | `project_inactive` / `account_inactive` / `media_unavailable` | Scheduling or arming not possible |
| 409 | platform arming codes (e.g. `tiktok_consent_required`, `tiktok_options_incomplete`, `telegram_channel_required`, …) | `arming_problems` of the publisher |
| 422 | field errors | Past date (`scheduled_at`), arming without/with past date (`auto_publish_enabled`), failed post armed without a new time, invalid overrides |

### New guarantee (Feature 024, FR-030–FR-033)

The editability decision and every write of the request happen atomically with respect to
any other writer (scheduler claim, manual publish, runner, another PATCH, delete):

- **PATCH first** → the new values are committed; a later claim re-checks its conditions on
  them (a future date is outside the window → not claimed).
- **Claim first** → the PATCH reads `publishing` and answers
  `409 publication_not_editable`; nothing it carried is written.
- **Never**: a publication left `scheduled` (or any other value written by the PATCH) while it
  has a `running` attempt started by a concurrent claim.
- Two concurrent valid PATCHes are serialized: both succeed, the last one committed wins.

If SQLite's writer lock cannot be obtained within the driver timeout (5 s), the request fails
with the existing generic internal error (no technical details), as any other writer would.

## Out of scope

`POST /api/publications/{id}/cancel` keeps its current behaviour, including its known
read-then-write window against the claim (documented in the spec's Assumptions).
