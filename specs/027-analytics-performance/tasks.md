---

description: "Task list for Feature 027 — Analytics & Performance"
---

# Tasks: Analytics & Performance

**Input**: Design documents from `/specs/027-analytics-performance/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/analytics-api.md, quickstart.md

**Tests**: requested explicitly. Every checkpoint has its own tests, which run in a targeted way
(`uv run pytest tests/test_analytics_<x>.py`, `npm test -- src/pages/analytics`).

**Organization**: by checkpoints A–I of [plan.md](plan.md). Each checkpoint is implemented,
tested, audited and closed with **one commit**, then work stops before the next one. Inside each
checkpoint the order is model/contracts → backend → frontend → tests → checks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no pending dependencies).
- **[Story]**: US1–US5 of spec.md. Infrastructure checkpoints with no single story carry no
  label.

## Closed decisions (apply to every task)

- `0` and "not available" are different: an unavailable metric has **no** `metric_values` row,
  and the API returns `value: null, available: false`.
- No cross-platform quantitative comparison. Common concepts are only for visual alignment:
  `likes` and `comments` are alignable; `views` and `shares` are not.
- Engagement exists only within one platform, with the fixed formula declared by its adapter. If
  any required component is missing, or the denominator is 0, it is "not available". In v1
  only YouTube has a formula: `(likeCount + commentCount) / viewCount`.
- OAuth and scopes are not touched.
  - Threads = `permission_required` (group `insights`).
  - Instagram = `basic` supported + `insights` `permission_required`.
  - TikTok = `not_supported`; Telegram = `not_supported` (its MTProto API offers metrics, but no adapter in v1); X = `not_applicable`.
- Only `published` publications whose succeeded attempt has `external_id` can be refreshed.
  There is no heuristic matching (title, date, search).
- Current original metrics are kept. Only documented deprecated metrics are excluded (YouTube
  `favoriteCount`).
- Real snapshots only, with no interpolation.
- Publishing has absolute priority: no read starts while an attempt is `running` or an armed
  publication is due within 10 minutes (or inside its overdue window).
- YouTube analytics uses `videos.list` (`part=statistics`) from the **general** quota bucket,
  with an internal limit of 200 units/day. It never touches the `videos.insert` bucket.
- `remote_deleted` only after two absences at least 1 h apart (first one → `remote_not_found`).
- No scraping and no unofficial APIs.

---

## Checkpoint A — Modelo de datos, catálogo y capacidades (Foundational)

**Goal**: persist snapshots, values and refresh state; declare catalog and adapters; compute
capabilities per account and group. Covers FR-001, 002, 005–010 and 024.

**Independent test**: migration up/down; deleting a post, media or account removes its
analytics rows; `GET /api/analytics/catalog` and `GET /api/projects/{id}/analytics/accounts`
return the expected states for each platform.

### Model / contracts

- [X] T001 Add `MetricSnapshot`, `MetricValue` and `PublicationMetricState` models in `backend/app/models.py`. Use the fields, indexes and `NEVER_REUSE_IDS` from data-model.md, and CHECK constraints for `trigger` (`automatic|manual`), `origin` (`public_counter|insight`), `status` (the 8 states in data-model.md) and `value >= 0`.
- [X] T002 Create migration `backend/migrations/versions/0020_analytics_snapshots.py` (upgrade/downgrade) for the three tables.
- [X] T003 Register `MetricSnapshot`, `MetricValue` (through its snapshot) and `PublicationMetricState` in the post-deletion path of `backend/app/deletion.py` (`POST_DEPENDENTS` or an explicit delete before `Publication`), so that deleting a post, media, account or project removes them.
- [X] T004 Add the Pydantic schemas `MetricValueRead`, `EngagementRead`, `RefreshStateRead`, `CapabilityRead`/`CapabilityGroupRead` and `CatalogRead` from contracts/analytics-api.md in `backend/app/analytics/schemas.py`.

### Backend

- [X] T005 Create `backend/app/analytics/__init__.py` and `backend/app/analytics/catalog.py` with the concepts `views`, `likes`, `comments` and `shares`. Each has a label, a definition and `alignable` (true only for `likes` and `comments`). There is no "comparable" field.
- [X] T006 Create `backend/app/analytics/adapters/base.py` with:
  - `MetricDef` (name, label, definition, origin, concept|None, group);
  - `ExcludedMetric` (name, reason);
  - `EngagementFormula` (numerator names, denominator name);
  - `FetchResult` (one of `ok(values)`, `not_found`, `rate_limited(retry_at|None)`, `unauthorized`, `permission_missing`, `transient`);
  - the `MetricsAdapter` protocol (`platform`, `metrics`, `excluded`, `groups: {group: permission|None}`, `engagement`, `batch_size`, `fetch(session, account_id, remote_ids)`).
- [X] T007 [P] Declare the YouTube adapter (no fetch yet) in `backend/app/analytics/adapters/youtube.py`:
  - group `basic` → `https://www.googleapis.com/auth/youtube.readonly`;
  - metrics `viewCount`→views, `likeCount`→likes, `commentCount`→comments, and `dislikeCount` with no concept;
  - `excluded = [favoriteCount: "deprecated by YouTube in 2015, always 0"]`;
  - formula `(likeCount + commentCount) / viewCount`; `batch_size = 50`;
  - the `viewCount` definition mentions the YouTube definition change of 2026-08-24 and that the value is kept as returned.
- [X] T008 [P] Declare the Instagram adapter (no fetch yet) in `backend/app/analytics/adapters/instagram.py`:
  - group `basic` → `instagram_business_basic`, with `like_count`→likes and `comments_count`→comments (`public_counter`);
  - group `insights` → `instagram_business_manage_insights`, with `views`, `reach`, `likes`, `comments`, `shares`, `saved` and `total_interactions` (`insight`, declared but never read);
  - `engagement = None`; `batch_size = 1`.
- [X] T009 [P] Declare the Threads adapter in `backend/app/analytics/adapters/threads.py`:
  - group `insights` → `threads_manage_insights`, with `views`, `likes`, `replies`→comments (with a definition note), `reposts`, `quotes` and `shares`;
  - `engagement = None`;
  - `fetch` never calls the network, and raises if it is invoked.
- [X] T010 Create `backend/app/analytics/adapters/registry.py` with platform → adapter for youtube, instagram and threads. It also holds the static capabilities, each with a fixed reason: tiktok → `not_supported` (no `video.list` scope and no public post ids), telegram → `not_supported` (no Telegram analytics adapter in this version), x → `not_applicable`.
- [X] T011 Implement `backend/app/analytics/capability.py`:
  - `account_capability(session, account)` → `{state, groups[{group, state, missing_permission}], reason}`, using connection status (missing → `not_connected`, not `connected` → `reconnect_required`) and the scopes really granted per group (YouTube/Instagram connection data or secret, without new network calls);
  - `is_refreshable` = at least one group `supported`.
- [X] T012 Create `backend/app/analytics/routes.py` with `GET /api/analytics/catalog` and `GET /api/projects/{project_id}/analytics/accounts`, and include the router in `backend/app/main.py`.

### Tests

- [X] T013 [P] Migration test in `backend/tests/test_analytics_migration.py`: upgrade/downgrade of 0020, and the CHECKs reject an invalid `status`, a negative `value` and an invalid `origin`.
- [X] T014 [P] Deletion test in `backend/tests/test_analytics_deletion.py`: deleting a post, a media with published posts and an account removes its snapshots, values and states, and leaves other publications intact.
- [X] T015 [P] Catalog and adapter declaration tests in `backend/tests/test_analytics_catalog.py`:
  - only `likes` and `comments` are alignable, and no concept exposes comparability;
  - every declared metric has a definition;
  - YouTube excludes `favoriteCount` with a reason;
  - only YouTube declares engagement;
  - the Threads `fetch` is never invoked.
- [X] T016 [P] Capability tests in `backend/tests/test_analytics_capability.py`:
  - YouTube connected → `supported`;
  - Instagram → `basic` supported + `insights` `permission_required`;
  - Threads → `permission_required` with the missing permission;
  - TikTok → `not_supported`; Telegram → `not_supported`; X → `not_applicable`;
  - an account without a connection → `not_connected`; a `reconnect_required` connection → `reconnect_required`.
- [X] T017 API test in `backend/tests/test_analytics_api_catalog.py`: shape of `GET catalog` and `GET accounts`, authentication required, and 404 for an unknown project.

### Checks

- [X] T018 Run T013–T017 and `uv run ruff check app/analytics` + `uv run mypy app/analytics` on the new files; audit and close Checkpoint A with one commit.

---

## Checkpoint B — Motor de refresco y YouTube

**Goal**: refresh rules, state transitions, the manual queue and the first real adapter
(YouTube). Covers FR-003, 004, 011, 013, 015 and 016.

**Independent test**: with a fake Google gateway, one cycle `run_refresh_cycle(now)` turns a
queued manual request into a snapshot with values, and each error lands in its state.

### Model / contracts

- [X] T019 [US2] Add the response schemas `RefreshQueued`, `ProjectRefreshResult` (`queued`, `in_cooldown`, `not_eligible`) and the error codes `refresh_cooldown` (with `available_at`) and `analytics_not_refreshable` (with `reason`) in `backend/app/analytics/schemas.py`.

### Backend

- [X] T020 [US2] Add `get_video_statistics(access_token, video_ids) -> dict[id, dict[str,int]]` in `backend/app/youtube_gateway.py`:
  - `videos.list` with `part=statistics` and comma-separated `id` (at most 50);
  - only numeric fields are whitelisted, and absent fields stay absent;
  - returned ids not found in `items` are reported separately;
  - existing errors are reused (`GoogleUnauthorized`, `GoogleUnavailable`, `GoogleRejected`);
  - a new `GoogleQuotaExceeded` is raised for `quotaExceeded`/`dailyLimitExceeded`/`rateLimitExceeded`.
- [X] T021 [US2] Implement `fetch` in `backend/app/analytics/adapters/youtube.py`:
  - credentials via `youtube_connections.get_valid_credentials`;
  - maps the gateway result to `FetchResult` (`ok` with only the declared metrics and `excluded` dropped, `not_found`, `unauthorized`/`reconnect_required`, `rate_limited` with `retry_at` = next 00:00 America/Los_Angeles, `transient`);
  - fixed, safe error messages with no tokens or bodies.
- [X] T022 [US2] Implement linking in `backend/app/analytics/refresh.py`:
  - `remote_link(publication)` returns the `external_id` of the succeeded attempt, or `not_linked` with its reason (warning code `remote_identity_unavailable`, `details.tiktok_mode = inbox_upload`, no id);
  - there is no matching by title, date or search.
- [X] T023 [US2] Implement eligibility and the queue in `backend/app/analytics/refresh.py`:
  - `request_manual_refresh(session, publication_id, now)`: 404 / 409 `analytics_not_refreshable` / 409 `refresh_cooldown` if `last_attempt_at > now − 15 min`; otherwise it sets `manual_requested_at` and `status = pending` (a request inside the cooldown is never queued);
  - `request_project_refresh(session, project_id, now)` → counts;
  - `due_publications(session, now)`: manual requests first (oldest), then automatic ones per data-model rule 2. The automatic part is wired in Checkpoint D; it is left as a separate function here.
- [X] T024 [US2] Implement the transitions in `backend/app/analytics/refresh.py`:
  - `apply_result(...)` per data-model rule 7: success → snapshot + one `metric_values` row per returned metric (a `0` is stored, an absent one is not) + `ok` + `next_attempt_at = captured_at + 24 h`;
  - transient → `stale` with exponential backoff (1 h × 2^(n−1), at most 24 h);
  - rate limit → `rate_limited`;
  - unauthorized → `reconnect_required`; permission → `permission_required`;
  - absence → `remote_not_found` (next + 1 h), and a second absence ≥ 1 h later → `remote_deleted`;
  - `manual_requested_at` is cleared once attempted;
  - nothing is ever written to `publications` or `publication_attempts`.
- [X] T025 [US2] Implement `run_refresh_cycle(session_factory, adapters, now, trigger_budget)` in `backend/app/analytics/refresh.py`:
  - groups by account into batches of `batch_size` and calls `adapter.fetch`;
  - keeps an in-memory per-platform pause (rate limit) that skips the rest of that platform's batches;
  - at most 200 publications per cycle;
  - a manual request blocked by a platform pause stays queued.
  This is synchronous and invocable from tests; the thread comes in Checkpoint D.
- [X] T026 [US2] Add `POST /api/publications/{publication_id}/analytics/refresh` and `POST /api/projects/{project_id}/analytics/refresh` to `backend/app/analytics/routes.py`. They only enqueue (202), optionally call `wake()` on the refresher if one exists in `app.state`, and never do network work in the request.

### Tests

- [X] T027 [P] [US2] YouTube gateway tests in `backend/tests/test_analytics_youtube_gateway.py`: statistics parsing, absent fields, an id missing from `items`, quota exceeded, 401, 5xx/network, and a batch of 50 in one call.
- [X] T028 [P] [US2] Link tests in `backend/tests/test_analytics_link.py`: published with id → linked; inbox, `remote_identity_unavailable`, a non-published publication and one without a succeeded attempt → not refreshable, with the reason; several attempts → only the succeeded one with an id.
- [X] T029 [P] [US2] Snapshot and value tests in `backend/tests/test_analytics_snapshots.py`: `0` is stored as a row with 0; an absent metric has no row; `favoriteCount` is never stored; `remote_id`, `source`, `trigger` and `captured_at` are recorded; a failure creates no snapshot.
- [X] T030 [P] [US2] Refresh state tests in `backend/tests/test_analytics_refresh_states.py`:
  - ok → 24 h; transient backoff 1 h/2 h/4 h… capped at 24 h, and `last_success_at` is kept;
  - `rate_limited` until the Pacific reset, with the rest of the platform skipped and other platforms unaffected;
  - `reconnect_required`;
  - `remote_not_found` → `remote_deleted` only on the second absence ≥ 1 h later, and a reappearance between the two returns to `ok`;
  - publications and attempts are never modified.
- [X] T031 [P] [US2] Manual refresh tests in `backend/tests/test_analytics_manual_refresh.py`: 202 queued; 409 cooldown with `available_at` inside 15 min; 409 not refreshable (no id, TikTok, Telegram, Threads); project refresh counts `queued`/`in_cooldown`/`not_eligible`; the request makes no network call.

### Checks

- [X] T032 Run T027–T031 (plus T014 if `deletion.py` changed again) and ruff/mypy on the changed files; audit and close Checkpoint B with one commit.

---

## Checkpoint C — Instagram

**Goal**: read the basic Instagram counters with the current permission. Covers FR-002, 006
and 007.

**Independent test**: with a fake Instagram gateway, an Instagram post gets `like_count` and
`comments_count`; a hidden like count is "not available"; the insights group makes no call.

### Backend

- [ ] T033 [US1] Add `get_media_counters(access_token, media_id) -> dict[str,int]` in `backend/app/instagram_gateway.py`:
  - `GET {GRAPH_ROOT}/{media_id}?fields=like_count,comments_count`;
  - absent fields stay absent;
  - classification reuses the existing error map: code 100 "does not exist" → not found; 4/17/32/613/80002 or HTTP 429 → rate limited; invalid token → unauthorized; network/5xx → transient; any other unrecognised code → transient (never deleted).
- [ ] T034 [US1] Implement `fetch` in `backend/app/analytics/adapters/instagram.py`:
  - one call per media, with credentials via `instagram_connections.get_valid_credentials`;
  - only the `basic` group is read;
  - rate limited → `retry_at = now + 1 h`, doubling up to 24 h (the backoff is applied by `refresh.py`);
  - fixed, safe messages.

### Tests

- [ ] T035 [P] [US1] Instagram gateway tests in `backend/tests/test_analytics_instagram_gateway.py`: counters; `like_count` absent; code 100 → not found; rate limit codes; 429; invalid token; unknown code → transient.
- [ ] T036 [P] [US1] Adapter and cycle tests in `backend/tests/test_analytics_instagram.py`: a snapshot with `like_count`/`comments_count`; a hidden like has no row and is not 0; no insights call is made; engagement is null for Instagram; an Instagram rate limit does not block YouTube in the same cycle.

### Checks

- [ ] T037 Run T035–T036 and ruff/mypy on the changed files; audit and close Checkpoint C with one commit.

---

## Checkpoint D — Refresco automático y prioridad de publicación

**Goal**: a background refresher with the 24 h / 90-day rules, the YouTube budget and
publishing priority. Covers FR-012, 014 and 017.

**Independent test**: with a fake clock and adapters, the refresher reads only what is due,
yields to publishing and survives errors.

### Backend

- [ ] T038 [US2] Add the read-only helper `publishing_imminent(session, now) -> bool` in `backend/app/automation.py`. It returns true when any `PublicationAttempt` is `running`, or any publication is `scheduled` + `auto_publish_enabled` with `scheduled_at <= now + 10 min` and inside `AUTO_PUBLISH_WINDOW`. The publishing scheduler does not change.
- [ ] T039 [US2] Complete the automatic eligibility in `backend/app/analytics/refresh.py`:
  - `published_at >= now − 90 days`;
  - status not in {`reconnect_required`, `permission_required`, `remote_deleted`};
  - `next_attempt_at` NULL or ≤ now;
  - order: `pending` first, then oldest `last_success_at`;
  - `reconnect_required` is re-evaluated when the connection is `connected` again.
- [ ] T040 [US2] Add the YouTube budget in `backend/app/analytics/refresh.py`: an in-memory counter of **general-bucket** units per Pacific day (1 per `videos.list` batch), capped at 200. Once the cap is reached, YouTube waits until the reset; other platforms continue.
- [ ] T041 [US2] Make `run_refresh_cycle` check `publishing_imminent` before each batch, in `backend/app/analytics/refresh.py`. If it is true, the cycle stops and queued manual requests stay queued. A batch already in flight is not aborted.
- [ ] T042 [US2] Create `backend/app/analytics/refresher.py`:
  - an `AnalyticsRefresher` daemon thread (tick every 5 min, `wake()`, clean `stop()`, an injectable clock and settings, like `Scheduler`);
  - a failed cycle is logged with only the class name and never stops the thread;
  - it ignores `AutomationSettings.automation_paused`.
- [ ] T043 [US2] Start the refresher after the `Scheduler` and stop it before it in `backend/app/main.py` (`app.state.analytics_refresher`), with settings that tests can disable.

### Tests

- [ ] T044 [P] [US2] Publishing priority tests in `backend/tests/test_analytics_priority.py`:
  - no read with a `running` attempt;
  - no read with an armed publication due in < 10 min or overdue inside its window;
  - a non-armed publication or one due later does not block;
  - manual requests stay queued and run once publishing finishes;
  - the publishing scheduler never consults analytics.
- [ ] T045 [P] [US2] Automatic refresh tests in `backend/tests/test_analytics_auto_refresh.py`:
  - at most 1 read per 24 h;
  - > 90 days → not automatic, but manual is allowed;
  - `remote_deleted`/`permission_required` are not retried;
  - the automation pause does not stop analytics;
  - the YouTube budget stops at 200 units/day and resets at 00:00 PT;
  - an Instagram rate limit does not affect YouTube.
- [ ] T046 [P] [US2] Refresher lifecycle tests in `backend/tests/test_analytics_refresher.py`: start/stop, `wake()` triggers a cycle, an exception in a cycle does not stop the thread, and logs carry no tokens.

### Checks

- [ ] T047 Run T044–T046 plus the scheduler test directly affected by the `automation.py` helper (`tests/test_scheduler_tick.py`), and ruff/mypy on the changed files; audit and close Checkpoint D with one commit.

---

## Checkpoint E — Pantalla base de Analytics por proyecto (MVP)

**Goal**: list the posts of a project with their original metrics, states, engagement and
refresh. Covers US1, US2, FR-018 and FR-019.

**Independent test**: in the UI, with a fake API, the Analytics page shows each kind of row
(metrics, not linked, permission required, not supported, not available on the platform,
stale, rate limited, remote deleted, cooldown) and never shows 0 for a missing metric.

### Model / contracts

- [ ] T048 [US1] Add `PostAnalyticsRow`, `PublicationAnalytics` (without `history` yet) and the query parameters of `GET posts` (without `sort`) in `backend/app/analytics/schemas.py`, following contracts/analytics-api.md.

### Backend

- [ ] T049 [US1] Implement in `backend/app/analytics/queries.py`:
  - `list_posts(session, project_id, platform?, account_id?, published_from?, published_to?)`: published publications, ordered by `published_at desc`;
  - each row uses the latest snapshot, expands **all** declared metrics (missing → `value: null, available: false`), and includes the concept, `content_type` (image/video from the content, text if `content_id IS NULL`), `age_days`, `link_state` + reason, capability state and refresh state (`pending` if there is no row);
  - no totals or aggregates.
- [ ] T050 [US1] Implement `engagement_for(adapter, values)` in `backend/app/analytics/queries.py`: the fixed formula, returning `available: false` if any component is missing or the denominator is 0, plus the formula text and the component values. Platforms without a formula → `null`.
- [ ] T051 [US1] Add `GET /api/projects/{project_id}/analytics/posts` and `GET /api/publications/{publication_id}/analytics` to `backend/app/analytics/routes.py`.

### Frontend

- [ ] T052 [P] [US1] Add the analytics types (`MetricValue`, `Engagement`, `RefreshState`, `Capability`, `PostAnalyticsRow`, …) in `frontend/src/types.ts`, and the client functions (`getAnalyticsAccounts`, `getAnalyticsPosts`, `getPublicationAnalytics`, `refreshPublicationAnalytics`, `refreshProjectAnalytics`, `getAnalyticsCatalog`) in `frontend/src/api.ts`.
- [ ] T053 [P] [US1] Add the analytics fakes (catalog, accounts, posts, refresh with cooldown) in `frontend/src/test-fake-api.ts`.
- [ ] T054 [US1] Add the route `p/:projectId/analytics` in `frontend/src/routes.tsx` and the "Analytics" entry in `frontend/src/shell/PrimaryNav.tsx`.
- [ ] T055 [US1] Create `frontend/src/pages/analytics/AnalyticsPage.tsx` with the page structure, data loading, a "Refresh project" button with the `queued`/`in_cooldown`/`not_eligible` result, and loading/empty/error states.
- [ ] T056 [P] [US1] Create `frontend/src/pages/analytics/CapabilityPanel.tsx`: one row per account with its state and groups (e.g. Instagram "Insights: permission required"), and fixed texts for `not_supported`, `not_available_on_platform`, `not_applicable`, `not_connected` and `reconnect_required`.
- [ ] T057 [US1] Create `frontend/src/pages/analytics/PostsTable.tsx`. It shows:
  - metrics with their original name (and common label as a secondary tag), with "Not available" (never 0) for `available: false`;
  - age, last read date, state, a link to the remote post and the "not linked" reason;
  - engagement with its formula and components, or "Not available";
  - a "Refresh" button per row that handles `refresh_cooldown` with its time.
  There is no cross-platform total or ordering.
- [ ] T058 [P] [US2] Create `frontend/src/pages/analytics/RefreshStatus.tsx`: an indicator for `ok`/`pending`/`stale`/`rate_limited`/`reconnect_required`/`permission_required`/`remote_not_found`/`remote_deleted`, with the last valid date and a link to Accounts when reconnection is needed. Reuse `ui/` components and the styles of `posts.css` or a new `frontend/src/pages/analytics/analytics.css`.

### Tests

- [ ] T059 [P] [US1] API tests in `backend/tests/test_analytics_api_posts.py`:
  - row shape;
  - `0` → `value 0`, absent → `null`/`available: false`;
  - `not_linked` with its reason;
  - TikTok/Telegram/Threads states;
  - YouTube engagement correct, null if a component is missing or views = 0, and null for Instagram;
  - no aggregate fields;
  - filters by platform, account and dates.
- [ ] T060 [P] [US1] Frontend tests in `frontend/src/pages/analytics/analytics.test.tsx`:
  - page with metrics, with "Not available" and with a real 0;
  - the capability panel per state, including partial Instagram;
  - the "not linked" row;
  - the visible engagement formula;
  - stale/rate limited/remote deleted states;
  - manual refresh, including cooldown;
  - empty project and API error.
- [ ] T061 [P] [US1] Nav/route test in `frontend/src/shell/shell.test.tsx` (or `frontend/src/routes.test.tsx`): the Analytics entry exists and navigates.

### Checks

- [ ] T062 Run T059–T061, `npm run typecheck`, and ruff/mypy on the backend files; review the UI manually on the safe instance (quickstart steps 1–6); audit and close Checkpoint E with one commit. **MVP completed.**

---

## Checkpoint F — Rankings y resumen por tipo de contenido (deferrable)

**Goal**: best posts within one platform, and medians by content type. Covers US3, FR-020 and
FR-021.

**Independent test**: ordering by a metric requires a platform; a cross-platform ranking is
rejected; types with n < 3 show "insufficient sample".

### Model / contracts

- [ ] T063 [US3] Add `sort`/`order` to the `GET posts` parameters, the `ranked` field to the row, the `ContentTypeSummary` schema, and the `ranking_requires_single_platform` error in `backend/app/analytics/schemas.py`.

### Backend

- [ ] T064 [US3] Implement ordering in `list_posts` in `backend/app/analytics/queries.py`:
  - `sort` is a metric of that platform or `engagement`;
  - it requires `platform`, and `account_id` must belong to it; otherwise 422 `ranking_requires_single_platform`;
  - unavailable metrics go last with `ranked: false`.
- [ ] T065 [US3] Implement `content_type_summary(session, project_id, platform, account_id?, dates?)` in `backend/app/analytics/queries.py`, using the latest snapshot:
  - per type: `posts_with_data`, `posts_total`, `median_age_days`, medians per metric and the engagement median, all within one platform;
  - `insufficient_sample` when < 3, with medians set to null.
- [ ] T066 [US3] Add `GET /api/projects/{project_id}/analytics/content-types` (with `platform` required) to `backend/app/analytics/routes.py`, plus the `sort` parameters on `GET posts`.

### Frontend

- [ ] T067 [P] [US3] Add `sort`/`order` and `getContentTypeSummary` to `frontend/src/api.ts`/`frontend/src/types.ts`, and their fakes to `frontend/src/test-fake-api.ts`.
- [ ] T068 [US3] Add a platform/account and period selector to `frontend/src/pages/analytics/AnalyticsPage.tsx`. The metric sort control (`PostsTable.tsx`) is enabled only when a platform is selected, and offers only that platform's metrics.
- [ ] T069 [US3] Create `frontend/src/pages/analytics/ContentTypeSummary.tsx`: a per-type table for the selected platform with n, median age and medians, and "Insufficient sample" when appropriate.

### Tests

- [ ] T070 [P] [US3] Backend tests in `backend/tests/test_analytics_rankings.py`: ordering within YouTube; 422 without a platform or with a foreign account; unavailable metrics last; engagement ordering only with available values.
- [ ] T071 [P] [US3] Backend tests in `backend/tests/test_analytics_content_types.py`: correct medians (odd/even); n < 3 → insufficient; text vs image vs video; never mixes platforms.
- [ ] T072 [P] [US3] Frontend tests in `frontend/src/pages/analytics/rankings.test.tsx`: the sort control is disabled without a platform; ranking and the type summary render; the insufficient sample message.

### Checks

- [ ] T073 Run T070–T072, `npm run typecheck`, and ruff/mypy on the changed files; audit and close Checkpoint F with one commit.

---

## Checkpoint G — Vista lado a lado de un mismo contenido (deferrable)

**Goal**: the same content shown per platform, aligned without comparing. Covers US4,
FR-009, FR-010 and FR-022.

**Independent test**: a content published on YouTube and Instagram shows `likes`/`comments`
aligned with their original names and the non-equivalence note; views/shares per platform; no
sums, averages, ordering or "best" marks.

### Model / contracts

- [ ] T074 [US4] Add the `ContentSideBySide` schema (`aligned[concept, cells]`, `per_platform`, `note`) in `backend/app/analytics/schemas.py`.

### Backend

- [ ] T075 [US4] Implement `content_side_by_side(session, content_id)` in `backend/app/analytics/queries.py`:
  - only `alignable` concepts go into `aligned`, keeping `metric_name` and the original definition (Threads `replies` with its note, for the future);
  - the rest go into `per_platform`;
  - cells follow the account order;
  - no aggregate, ordering or "best" fields.
- [ ] T076 [US4] Add `GET /api/contents/{content_id}/analytics` to `backend/app/analytics/routes.py`.

### Frontend

- [ ] T077 [P] [US4] Add `getContentAnalytics` and its types to `frontend/src/api.ts`/`frontend/src/types.ts`, and the fake to `frontend/src/test-fake-api.ts`.
- [ ] T078 [US4] Create `frontend/src/pages/analytics/SideBySide.tsx`: one column per publication, aligned rows with the common label and the original name, a note "Not quantitatively equivalent across platforms", and the non-aligned metrics per platform. There is no highlight, ordering or total.
- [ ] T079 [US4] Integrate `SideBySide` into the media/post detail (`frontend/src/pages/library` media view or `frontend/src/pages/posts/PostDetail.tsx`, whichever already shows the content's publications) and link it from `PostsTable.tsx`.

### Tests

- [ ] T080 [P] [US4] Backend tests in `backend/tests/test_analytics_side_by_side.py`: only likes/comments are aligned; views/shares per platform; a platform without data → `available: false`; no aggregate fields; a single publication; a nonexistent content → 404.
- [ ] T081 [P] [US4] Frontend tests in `frontend/src/pages/analytics/side-by-side.test.tsx`: original names visible, the note present, no "best" mark or highlight on the larger value, and no totals.

### Checks

- [ ] T082 Run T080–T081, `npm run typecheck`, and ruff/mypy on the changed files; audit and close Checkpoint G with one commit.

---

## Checkpoint H — Evolución histórica (deferrable)

**Goal**: the evolution of a publication from real snapshots. Covers US5 and FR-023.

**Independent test**: with N snapshots, the chart shows exactly N points in time order; with 1
there is no line.

### Model / contracts

- [ ] T083 [US5] Add `history` (`captured_at`, `trigger`, `source`, `remote_id`, `values`) to `PublicationAnalytics` in `backend/app/analytics/schemas.py`.

### Backend

- [ ] T084 [US5] Implement `publication_history(session, publication_id)` in `backend/app/analytics/queries.py`: all real snapshots from oldest to newest, with their original values, and no interpolation or filling. Include it in `GET /api/publications/{id}/analytics`.

### Frontend

- [ ] T085 [P] [US5] Add `history` to the types in `frontend/src/types.ts` and the fake to `frontend/src/test-fake-api.ts`.
- [ ] T086 [US5] Create `frontend/src/pages/analytics/EvolutionChart.tsx`:
  - simple SVG with one series per metric, using only real points and marking "not available" points as gaps (no 0 and no joining line);
  - with 1 snapshot, a single point and no line;
  - a table alternative for accessibility;
  - the YouTube `viewCount` definition shows the note about the definition change of 2026-08-24.
- [ ] T087 [US5] Open `EvolutionChart` from the post detail in `frontend/src/pages/analytics/PostsTable.tsx` (an expandable row or a dialog using the existing `ui/` pattern).

### Tests

- [ ] T088 [P] [US5] Backend tests in `backend/tests/test_analytics_history.py`: order; all snapshots; a metric missing in one snapshot is missing only in that one; there are no synthetic points.
- [ ] T089 [P] [US5] Frontend tests in `frontend/src/pages/analytics/evolution.test.tsx`: N points; 1 snapshot → no line; gaps for unavailable values; the YouTube note visible.

### Checks

- [ ] T090 Run T088–T089, `npm run typecheck`, and ruff/mypy on the changed files; audit and close Checkpoint H with one commit.

---

## Checkpoint I — Documentación y checks finales

**Goal**: documentation and the closing checks for the feature.

- [ ] T091 [P] Create `docs/analytics.md`:
  - the per-platform capabilities and their reasons;
  - the original metrics and their definitions, including the YouTube `viewCount` change and the `favoriteCount` exclusion;
  - alignment vs comparison;
  - the fixed engagement formula;
  - the refresh rules (24 h, 90 days, 15 min, publishing priority, 200 units/day from YouTube's general bucket, `remote_deleted` with double confirmation);
  - known limitations (Instagram/Threads insights, TikTok, Telegram).
- [ ] T092 [P] Update `README.md` with an Analytics section and a link to `docs/analytics.md`.
- [ ] T093 Update `specs/027-analytics-performance/spec.md` (Status) and mark the closed checkpoints in this `tasks.md`.
- [ ] T094 Run the closing checks once: backend `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`; frontend `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`; and `git diff --check`. Do not run the full pytest/vitest suites (CI runs them).
- [ ] T095 Security review of the diff: no tokens in logs or errors, no remote bodies stored, no new scopes, no scraping. Then do the manual validation from quickstart.md on the safe instance, and close Checkpoint I with one commit.

---

## Dependencies & Execution Order

- **A → B → C**, **A → B → D**: C and D depend on B (`refresh.py`, `FetchResult`). C and D are independent of each other but share `refresh.py`, so do them in sequence C → D to avoid conflicts.
- **E** depends on A + B (rows, states, refresh endpoints). It works without C (Instagram as `basic` with no reads) and without D (manual refresh only), but the MVP closes with A–E complete.
- **F, G, H** depend only on A + B + E (queries, schemas, page) and are independent of each other. Each can be deferred without breaking the MVP.
- **I** goes last; T091 documents whatever has been closed.

## Parallel Opportunities

- A: T007/T008/T009 (adapter declarations) and T013–T016 (tests in different files).
- B: T027–T031. C: T035–T036. D: T044–T046.
- E: T052/T053 (frontend types/fakes) in parallel with the backend T049–T051; T056/T058 components; T059–T061 tests.
- F/G/H: their tests in parallel; the three checkpoints themselves can go in any order after E.

## Implementation Strategy

1. **MVP**: A → B → C → D → E, one commit per checkpoint, stopping after each to audit.
2. **Derived views**: F, G and H in any order, each independently deferrable.
3. **Closing**: I, with the global checks run once.
