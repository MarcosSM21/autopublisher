# API contracts — Feature 019

Only changes and the exact use of existing endpoints. All other endpoints are used as-is.

## 1. Create media drafts — existing, no change

`POST /api/contents/{content_id}/publications`

Feature 019 always sends **only** per-target explicit overrides (snapshot), no date, no
arming:

```json
{
  "account_ids": [3, 7, 9],
  "targets": {
    "3": { "description_override": "Caption", "hashtags_override": ["a"], "title_override": "Video title" },
    "7": { "description_override": "Caption", "hashtags_override": ["a"] },
    "9": { "description_override": "", "hashtags_override": [] }
  }
}
```

All-or-nothing and error shape unchanged (017). `201` → list of drafts (status
`unscheduled`).

## 2. Create text drafts — existing, no change

`POST /api/projects/{project_id}/text-publications` with `{account_ids, description,
hashtags}` (no `scheduled_at`, no `auto_publish_enabled`).

## 3. Content usage — extended response

`GET /api/contents/{content_id}/usage` and `Content.usage` in `GET
/api/projects/{id}/contents` / `GET /api/contents/{id}`:

```json
{
  "usage": {
    "used": true, "publication_count": 5, "published_count": 1, "awaiting_count": 0,
    "scheduled_count": 2, "platforms": ["youtube"], "last_published_at": "…",
    "draft_count": 1, "attention_count": 1, "upcoming_count": 1,
    "next_scheduled_at": "2026-10-21T16:00:00Z", "cancelled_count": 1
  },
  "publications": [
    {
      "publication_id": 12, "platform": "tiktok", "account_id": 9, "account_name": "…",
      "status": "scheduled", "scheduled_at": "…", "published_at": null,
      "created_at": "…", "updated_at": "…", "uncertain": false, "external_url": null,
      "display_state": "scheduled_automatic",
      "inherits": { "title": true, "description": false, "hashtags": false },
      "consent_covers_caption": true
    }
  ]
}
```

Read-only, no network, no writes. Additive: existing clients keep working.

## 4. Update publication — refined for FAILED

`PATCH /api/publications/{id}`

| Case | Body | Result |
|---|---|---|
| Reschedule (019 UI) | `{"scheduled_at": "<future>", "auto_publish_enabled": true}` | FAILED/UNSCHEDULED/SCHEDULED → SCHEDULED armed |
| Move to drafts (FAILED) | `{"scheduled_at": null}` | FAILED → UNSCHEDULED (even when the current value is already `null`; uncertain → `409 check_result_first`) |
| Edit schedule (019 UI) | `{"scheduled_at": "<future>", "auto_publish_enabled": true}` | stays SCHEDULED, armed |
| Publish automatically (legacy manual) | `{"auto_publish_enabled": true}` | SCHEDULED armed |
| Customize / Use the media's caption | overrides (`null` = inherit) | unchanged semantics |

New error: `409 {"code": "check_result_first", "message": "Check the result first.",
"fields": [{"field": "scheduled_at", …}]}` for FAILED when the latest attempt of the
content+account pair is uncertain.

Existing errors unchanged (`publication_not_editable` for PUBLISHING/PUBLISHED/AWAITING,
`publication_cancelled`, past date, arming problems such as `tiktok_consent_required`).

## 5. Final-action sequence per Post (client orchestration, existing endpoints)

Pre-validation (no writes, before any execution):
1. `flushAll()` autosaves; any `error` → summary.
2. For each Draft: `GET /publications/{id}/publish-check` (local, read-only). Problems other
   than `tiktok_consent_required` → summary. `tiktok_consent_required` → summary only if the
   local declaration is not accepted for the current fingerprint.
3. Schedule: date is in the future (local check; backend re-checks).

Execution (sequential, in set order; a failure never stops the rest):
- **Now**: (TikTok Direct Post) `POST /publications/{id}/tiktok-consent` →
  `POST /publications/{id}/publish {confirm_remote_checked:false}`. Error before start →
  "Didn't start" + message.
- **Schedule**: (TikTok Direct Post) `tiktok-consent` → `PATCH {scheduled_at,
  auto_publish_enabled:true}`. Error → Post stays in its real state (normally Draft).

No new endpoint.

## 6. Retry with acknowledgement — existing

`POST /publications/{id}/publish {"confirm_remote_checked": true}` only from the
`Check result` Dialog (`Publish again`) after the explicit acknowledgement that the Post was
not published (006 FR-041, spec FR-073a). While the result stays uncertain, `PATCH`
reschedule / move to drafts keep returning `409 check_result_first`, and direct Retry
(`confirm_remote_checked: false`) keeps returning the existing `remote_check_required`.
