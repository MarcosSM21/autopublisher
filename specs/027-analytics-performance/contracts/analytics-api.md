# Contract: Analytics API (Feature 027)

All endpoints require the existing authenticated session. Errors use the existing
`{code, message}` shape. Times are UTC ISO 8601. `MetricValue` never carries `0` for "not
available": an unavailable metric is listed with `value: null, available: false`.

## Shared shapes

```text
MetricValue   { name, label, value: int|null, available: bool, origin, concept: str|null, definition }
Engagement    { available: bool, value: float|null, formula: "(likeCount + commentCount) / viewCount",
                components: { likeCount: int|null, commentCount: int|null, viewCount: int|null } }
             | null   # platform without a declared formula
RefreshState  { status, last_success_at, last_attempt_at, next_attempt_at, manual_pending: bool,
                error_code, error_message, cooldown_until }
              # status ∈ pending | ok | stale | rate_limited | reconnect_required |
              #          permission_required | remote_not_found | remote_deleted (no `error`)
Capability    { state, groups: [{ group, state, missing_permission: str|null }], reason: str|null }
```

## Catalog

`GET /api/analytics/catalog` → `{ concepts: [{key, label, definition, alignable}], platforms:
[{platform, metrics: [...], engagement: {numerator, denominator}|null}] }`

## Capabilities

`GET /api/projects/{project_id}/analytics/accounts` → `[{account_id, platform, label,
capability: Capability}]`

## Posts list (US1, US3 rankings)

`GET /api/projects/{project_id}/analytics/posts`

Query: `platform?`, `account_id?`, `published_from?`, `published_to?`, `sort?`, `order?=desc`.

- Without `sort`: ordered by `published_at desc`; any mix of platforms is allowed.
- With `sort` (a metric name of that platform, or `engagement`): **requires `platform`** (and
  `account_id` must belong to it). Otherwise `422 ranking_requires_single_platform`. Posts with
  the metric unavailable come last, flagged `ranked: false`.
  - `sort` must be a metric this version reads for the platform (a group it reads), or
    `engagement` only if the platform declares a formula; otherwise `422 validation_error`
    (field `sort`).
  - Ranked rows (`ranked: true`) are ordered by the value only (`order` desc/asc). Ties, and
    the unranked rows, keep the default order: `published_at desc`, then `publication_id desc`.
  - The value is the latest valid snapshot's; a real `0` is ranked, an absent metric never is.
    Engagement ranks only posts where it is available.
  - The period filters are inclusive UTC days of **publication**, never of capture.

Row: `{publication_id, content_id|null, content_type: image|video|text, title, platform,
account_id, published_at, age_days, remote_url|null, link_state: linked|not_linked,
not_linked_reason|null, capability_state, metrics: [MetricValue], engagement, refresh:
RefreshState|null, captured_at|null, ranked: bool|null}` (`ranked` is null without `sort`)

The response has no totals, averages or cross-platform aggregates.

## One publication (US1, US5)

`GET /api/publications/{publication_id}/analytics` → the row above plus
`history: [{captured_at, trigger, source, remote_id, values: [{name, value, origin}]}]`
(real snapshots only, oldest first).

## Content-type summary (US3)

`GET /api/projects/{project_id}/analytics/content-types?platform=…&account_id?&published_from?&published_to?`

`platform` is required (`account_id` must belong to it, else `422
ranking_requires_single_platform`). Uses the latest snapshot per publication. Response, only for
the types with posts (order image, video, text; text = post without media):
`[{content_type, posts_with_data, posts_total, insufficient_sample: bool (posts_with_data < 3),
median_age_days|null, medians: [{name, label, concept, count, insufficient_sample, value|null}],
engagement_median: {count, insufficient_sample, value|null}|null}]`.

- `count` is the number of posts of that type with that metric; the median uses only them (a
  real `0` counts, an absent metric does not). With `count < 3`, `insufficient_sample: true`
  and `value: null`.
- `median_age_days` is over the posts with data (context only, no normalization by age).
- `engagement_median` is null for a platform without a formula.

## Side by side (US4)

`GET /api/contents/{content_id}/analytics` →
`{content_id, aligned: [{concept, label, definition, cells: [{publication_id, platform,
account_id, metric_name|null, value|null, available, definition|null}]}], per_platform:
[row of §Posts list without `ranked`, its `metrics` limited to the non-aligned ones], note}`.

- "The same content" is only the local `content_id` of the publications (status
  `published`); never title, caption, date, URL or text similarity. Text posts
  (`content_id IS NULL`) have no side-by-side view.
- Only `alignable` concepts appear in `aligned`, and only if some publication's platform
  declares a metric for them. A cell keeps the platform's original metric name and
  definition; `metric_name: null` means the platform has no such metric (e.g. TikTok, not
  supported); an absent value is `value: null, available: false`, never 0.
- Views, shares, platform-only metrics and engagement stay in their own `per_platform` row.
- There are no sums, averages, differences, ordering or "best" flags. `cells` and
  `per_platform` follow account order (`account_id`, then `publication_id`).
- One publication is a valid view; a media with no published publication returns empty
  `aligned`/`per_platform`; an unknown content is `404`.

## Refresh

- `POST /api/publications/{publication_id}/analytics/refresh` →
  - `202 {queued: true}`;
  - `409 refresh_cooldown {available_at}`: the last attempt was less than 15 min ago; the
    request is **not** queued;
  - `409 analytics_not_refreshable {reason}` (not linked or capability not supported);
  - `404`.
- `POST /api/projects/{project_id}/analytics/refresh` →
  `202 {queued: int, in_cooldown: int, not_eligible: int}`. Publications in cooldown are
  counted in `in_cooldown` and not queued; queued ones become `pending`.

The work is done by the background refresher (data-model §Refresh rules), never inside the
request.
