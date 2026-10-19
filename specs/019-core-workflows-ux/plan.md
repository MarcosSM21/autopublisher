# Implementation Plan: Core Workflows UX Redesign

**Branch**: `019-core-workflows-ux` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/019-core-workflows-ux/spec.md`

Companion artifacts: [research.md](research.md) (decisions R-01…R-14),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md).

## Summary

Feature 019 replaces the legacy Library, Media detail, Distribute, queue and publication
detail screens with redesigned surfaces on top of the 018 foundation. It is mostly frontend
work. The backend changes are small and additive:

1. `ContentUsageRead` / `AssetPublicationRead` gain display-state-based counts and fields.
2. `PATCH /publications/{id}` allows Failed → Scheduled (armed) or Draft when the latest
   result is not uncertain (R6). This is the only lifecycle change.

Publish becomes a task route (`…/library/:mid/publish`, `…/posts/new`) with one controller
for media and text posts. Its identity survives reloads through `?posts=<ids>`. The client
orchestrates the existing per-Post endpoints: create drafts with explicit snapshot overrides;
validate everything before any execution; record the single TikTok declaration right before
each Post's action; run the actions sequentially and report partial results without rollback.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript ~6.0 + React 19.2 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy, Alembic; React Router 8.4, `@radix-ui/react-dialog` 1.1.23. No new dependencies.

**Storage**: SQLite local + local filesystem. No migration in 019.

**Testing**: pytest (backend), Vitest + Testing Library + jsdom (frontend)

**Target Platform**: local web app (browser), single user

**Project Type**: web application (`backend/` + `frontend/`)

**Performance Goals**: individual-user volumes (hundreds of Media, thousands of Posts). Library and Posts load in one listing request each, with no N+1 queries. Publish adds no network work beyond what each Post action already does.

**Constraints**:
- The backend owns lifecycle and display-state semantics.
- The URL owns navigable state.
- No persisted batch.
- No duplicated platform validation.
- No backend pagination.
- No thumbnail pipeline.
- Nothing from Feature 020.

**Scale/Scope**: 6 frontend surfaces (Library, Media detail, Publish task, Posts List/History/Calendar, Post detail, Text post), 2 backend read-model extensions, 1 lifecycle transition.

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I. Simplicity / scope | PASS | Reuses existing endpoints. No batch endpoint, no new entity. Small hooks instead of libraries. Text posts reuse the Publish controller. |
| II. Spec-Driven | PASS | Approved spec. Contradictions are reported below (C1–C6), not resolved silently; C1 resolved in spec FR-073a. |
| III. Modular architecture | PASS | Platform rules stay in the publishers. The frontend maps backend problems and options; it does not re-validate. Platform cards are per platform. |
| IV. Security | PASS | Post ids in URLs are local identifiers. Technical details stay under disclosures. No secrets in `submitted` (verified per publisher; see Security). |
| V. Quality | PASS | Targeted tests per block, regression tests for the lifecycle change. No silent loss: partial results stay visible and every Post stays in its real state. |
| VI. Git | PASS | Small commits per block (defined in tasks). Docs updated: `docs/design-system.md` and README Posts/Publish sections. |

Re-check after Phase 1: **PASS**, with no violations to justify.

## 1. Architecture overview

```text
URL (router) ── owns: project, section, selected media/post, view/week, filters, ?posts=
   │
   ├─ ProjectLayout (018): project + shared project overview (readiness) + reloadOverview
   │
   ├─ Library page ──── listContents (usage incl. new counts) ── MediaDetail (DetailSurface)
   │                                                          └─ getContent + getContentUsage
   ├─ Publish task (media|text) ── usePublishTask (reducer + orchestration)
   │      Compose: account-health + platforms + presets + usage (blocking/resume)
   │      Review:  getPublication×set → per card: options, publish-check, Creator Info
   │      Action:  tiktok-consent → publish | PATCH arm   (sequential, per Post)
   │
   └─ Posts page ── usePostsData (listPublications, polling) ── List | History | Calendar
                                                  └─ PostDetail (DetailSurface) reads the same list
Backend: existing endpoints; +usage fields; +FAILED transition in PATCH.
```

Single sources of truth:
- Post state: backend `display_state`.
- Readiness: the project overview plus account health.
- Lists: one listing request per page.
- Publish set: `?posts=`.
- Unfinished input: React state (Compose, open editors).

## 2. Route map

See [contracts/ui.md §1](contracts/ui.md).

`routes.tsx` changes:
- Add `library/:mediaId/publish` and `posts/new`, declared before the optional-id routes,
  with `handle: { taskMode: true }`.
- `AppShell` reads `useMatches()` and hides the bottom nav on `sm` when `taskMode` is set.
- `PostsPage` handles `view`, `week`, `q`, `account` query parameters.
- `parseId("new")` already returns null. The explicit route avoids a "not found".

## 3. Frontend component map

Proposed layout (pages own their surfaces; shared platform code under
`components/platform/`):

```text
frontend/src/
├── ui/                     + Field.tsx, ChoiceGroup.tsx, PageActions.tsx
│                           ~ DetailSurface.tsx (panelFrom, actions, scroll), breakpoints.ts (+xl)
├── shell/AppShell.tsx      ~ taskMode → hide bottom nav (sm)
├── pages/
│   ├── LibraryPage.tsx     ~ becomes the container (toolbar, import, grid, detail)
│   ├── library/            MediaGrid, MediaCard, LibraryToolbar, ImportPanel, LibraryDropzone,
│   │                       MediaDetail, MediaContentEditor, InheritanceWarning, MediaUsage,
│   │                       FileDetails, usage-indicator.ts, library.css
│   ├── publish/            PublishMediaPage, PublishTextPage (thin route wrappers),
│   │                       PublishTask (layout), usePublishTask.ts (reducer+orchestration),
│   │                       publish-set.ts (URL parse/serialize/validate), snapshot.ts,
│   │                       destinations.ts (availability + reasons),
│   │                       compose/ DestinationList, PresetPicker, PresetsDialog, CommonContent,
│   │                               DestinationCustomize
│   │                       review/ ContentByDestination, EditContentDialog, PlatformDetailsList,
│   │                               WhenSection, ErrorSummary, ResultsSection, FinalActions
│   │                       publish.css
│   ├── PostsPage.tsx       ~ container (header, ViewSwitch, toolbar, view, detail)
│   └── posts/              usePostsData.ts, sections.ts (grouping/precedence), readiness.ts,
│                           DailyList, HistoryList, PostRow, CalendarView, CalendarWeek,
│                           CalendarAgenda, calendar.ts (anchors, week math), PostDetail,
│                           StatusActionPanel, post-actions.ts (FR-071 table), ActionDialog,
│                           CheckResultDialog, PostWhen, PostContent, sent-content.ts,
│                           Activity, NewPostMenu, posts.css
└── components/
    ├── platform/           PlatformDetails (dispatcher + card + state), useAutosave.ts,
    │                       AutosaveRegistry.tsx, platform-state.ts (problems → human summary),
    │                       YouTubeDetails, InstagramDetails, ThreadsDetails, TikTokDetails,
    │                       TelegramDetails, TikTokDeclaration, tiktok-declaration.ts
    ├── MediaPreview.tsx    reused
    ├── TikTokInboxDelivery.tsx  reused in Post detail (Check status)
    └── *ConnectionPanel.tsx     untouched (Accounts)
```

Fate of existing components:

| Component | Fate |
|---|---|
| `MediaPreview`, `TikTokInboxDelivery`, `StatusBadge`, `Disclosure`, `Dialog/Drawer/Sheet`, `EmptyState`, `ErrorState`, `Skeleton`, `Card`, `Button`, `IconButton` | Reused |
| `ContentImport` | Adapted into `ImportPanel` + `LibraryDropzone` (keeps the import call and per-file results) |
| `AssetFile` | Adapted into `FileDetails` (same metadata inspect/remove calls) |
| `YouTube/Instagram/ThreadsPublishOptions` | Adapted into `*Details` with autosave. The field components (e.g. `YesNo`) are kept; the form/Save button goes away |
| `TikTokPublishOptions` | Adapted into `TikTokDetails`: mode choice, Creator Info, fields, autosave. The persisting consent checkbox is **removed** and replaced by `TikTokDeclaration` (local) |
| `PublicationAttempts` | Adapted into `Activity`: human events first, a second disclosure for technical details |
| `Distribute` | Replaced. `PresetManager` logic moves to `PresetsDialog`; the `toOverrides`/`textFields` helpers move to `snapshot.ts`; the result panel is removed |
| `PublicationQueue`, `PublicationDetail`, `PublicationControls`, `PublishNowDialog`, `AutoPublishConsent`, `AutoPublishBadge`, `TextPublicationCreate`, `useLivePublication` | Replaced and deleted at the end of migration (§13) |
| `ContentLibrary`, `ContentDetail`, `AssetUsage` | Replaced and deleted |

No wrappers around Radix or 018 primitives beyond the listed additions.

### Library

- `LibraryPage` (container): `listContents(projectId)` once; reloads after import and edit.
  Search and filters are local React state of the container (not in the URL; no deep links
  for filters in 019), applied client-side over title, filename, description and hashtags.
  The grid stays mounted when `:mediaId` changes, so they are kept.
- `MediaGrid` is a `<ul>` with `display:grid; grid-template-columns: repeat(auto-fill,
  minmax(clamp(140px, 22vw, 200px), 1fr))` on the list container. That yields 2 columns at
  375 px, about 4 at 768 px and 5–6 at desktop with no panel. With the side panel open
  (≥1280 px) the container narrows and the column count drops on its own.
- `MediaCard` is one `<Link>`: preview, duration badge, title or filename, one indicator
  (`usage-indicator.ts`, data-model §1). The selected card gets `aria-current="true"` and a
  strong outline.
- `ImportPanel`: `Import media` triggers a hidden `<input type=file multiple>` directly.
  The panel shows the progress and the aggregate plus per-file results, and can be dismissed.
  `LibraryDropzone` listens for drag events on the page container (md+) only. The empty state
  is an `EmptyState` with a large dropzone and a single primary button.

### Media detail

- `DetailSurface panelFrom="xl"` with `actions` (sticky primary action on `sm`).
- Order: `MediaPreview` → identity (title/filename, type, duration) → primary action →
  `MediaContentEditor` → `MediaUsage` → `FileDetails` (Disclosure).
- Primary action:
  - `draft_count === 0` → `Publish…`.
  - Otherwise `Continue publishing · N drafts`, plus the drafts' platforms from usage rows.
  - Disabled with its reason when the project is inactive or `file_available === false`.
- `MediaContentEditor`: one block, Edit → Save/Cancel (not autosave: it is the Media's own
  metadata and the inheritance warning needs a deliberate save). See §12 for the warning and
  the TikTok Dialog.
- `MediaUsage`: groups rows by `display_state` (§4 precedence, without readiness), each row
  linking to `/posts/:id`. Published shows the last 3 plus `Show all`; Cancelled shows only a
  count.

## 4. Backend change map

| File | Change |
|---|---|
| `backend/app/schemas.py` | `ContentUsageRead` + `draft_count`, `attention_count`, `upcoming_count`, `next_scheduled_at`, `cancelled_count`. `AssetPublicationRead` + `display_state`, `inherits`, `consent_covers_caption`. A small `FieldInheritanceRead` model. |
| `backend/app/asset_library.py` | `usage_by_content(session, project_id, ids, *, now, paused)`: one extra query over non-history Posts, evaluated with `post_display_state`. `get_content_usage` computes `display_state` (latest attempt already loaded), `inherits` and `consent_covers_caption` (one query on `TikTokPublicationOptions` for the TikTok ids). Add `ClockDep` and `is_paused`. |
| `backend/app/contents.py` | Pass `now`/`paused` through `list_contents` / `content_read`. |
| `backend/app/publications.py` | `ensure_editable` (now receiving `session`): for `FAILED`, the mere presence of `scheduled_at` in the body (even `null == null`) or arming counts as a scheduling change; allow it unless `requires_remote_check`, then raise `ConflictError("check_result_first", "Check the result first.")` with field `scheduled_at`. `update_publication`: for `FAILED`, when `scheduled_at` is in the fields, always transition (non-null → `SCHEDULED` after `ensure_future` and `ensure_can_prepare`; null → `UNSCHEDULED`), `disarm()`, then `clear_auto_publish_error()`, then the existing arming path. `publishing` already imports `publications`, so `requires_remote_check` moves (unchanged) to `post_state.py` next to `needs_manual_review` and is re-exported from `publishing` for its current callers. This avoids an import cycle. |
| `backend/app/publishing.py` | No behaviour change. |
| `backend/app/scheduler.py`, publishers, `overview.py`, `tiktok_*` | No change. |

No migration. No new router. No change to Reactivate.

## 5. Publish state model

`usePublishTask(mode, projectId, mediaId?)` is a `useReducer` plus orchestration effects.

| Phase | Lives in React | Lives in URL | Lives in backend | After reload |
|---|---|---|---|---|
| `loading` | — | `?posts` (maybe) | — | recomputed |
| `composing` | `selected`, `common`, `custom`, `presetNotice`, field errors | none | nothing written | **lost** (local exploration only; FR-019). The browser's `beforeunload` prompt applies only when Compose is dirty. |
| `creating` | busy flag | none | create request | if it succeeded before the reload, Resume (media) finds the drafts; text Compose restarts (see C3) |
| `task.reviewing` | open editors, TikTok declaration per Post, autosave queue, error summary | `?posts=` | Drafts + options | Review rebuilt from `?posts=`; declarations reset (by design, R5) |
| `task.committing` | per-Post step `{state: queued\|consent\|starting\|scheduling\|done\|error, message}` | `?posts=` | consent, publish/patch per Post | rebuilt from real states: started Posts appear in Results, unstarted ones remain Drafts in Review |
| `task.result` (Now) | polling timer | `?posts=` | Posts `publishing…` | rebuilt; polling resumes for `publishing` members |
| `task.result` (Schedule partial) | per-Post error messages | `?posts=` | some Scheduled, some Draft | rebuilt: Scheduled in Results, Drafts back in Review with the CTA |
| mixed set | — | `?posts=` | mixed | Results section + "Still to finish" Review (contracts/ui.md §3) |

Transitions:

```text
loading ─(no drafts / text)→ composing ─Continue→ creating ─201→ task(replace ?posts=)
        ─(drafts or ?posts)→ task                      └─4xx→ composing (errors kept)
task ─CTA→ validate ─fail→ task(+ErrorSummary, focus)
                     └ok→ committing ─each Post→ task(partitioned again by real state)
task ─Finish later→ flushAll → navigate(/posts)   (Drafts section)
task ─add destination→ create 1 draft (media: POST contents/{mid}/publications with snapshot
      | text: POST text-publications) → replace ?posts
task ─remove destination (confirm)→ POST cancel → drop id → replace ?posts
      + keep the id in React state as "removed from this task" (never persisted)
task ─re-add that account without reload → POST reactivate of exactly that id (existing rules:
      no date → Draft) → add id; on 409 → message, nothing created
task ─re-add after reload / no known removed id → create a new draft with the current
      snapshot (never look up historical Cancelled Posts)
task ─Add to this task (active Draft of this Media outside ?posts) → add its id; no write
```

The CTA count is `review.length` (Drafts only). After an action the partition is recomputed
from fresh `getPublication` results, never from assumptions.

## 6. Publish-set identity

Mechanism: `?posts=` (research R-02; format and validation in contracts/ui.md §2).

- **Parse** with `parseId` per item; order kept; duplicates dropped; limit 50.
- **Load** with `Promise.all(ids.map(getPublication))`. A 404, a Post of another project or,
  in media mode, `content_id !== mid` (text mode: `content_id !== null`) drops the id. The
  URL is rewritten with `replace` and a notice is shown.
- **Write** with `replace` after Continue, add/remove/re-add, and dropped ids. Resume
  without `posts` resolves the Media's drafts from `getContentUsage(mid)` (`display_state ===
  "draft"`), in usage order (newest first) re-sorted by id, then rewrites the URL.
- **Mixed render**: partition by `display_state`. Results come first ("3 published · 1
  failed", one row per Post with its human state and `Open post`). Then comes "Still to finish
  · N" with Platform details, When and the CTA for the Drafts only.
- **Never** uses "all Posts of the Media" after the set exists. The Media-drafts lookup
  happens only when `?posts` is absent.
- Back/forward: each `replace` keeps one history entry per task. Back leaves the task.

## 7. Data loading and polling

| Data | Where | Frequency |
|---|---|---|
| Media list (+usage) | Library | once, plus after import/edit |
| Content + usage | Media detail | on open, plus after edit |
| Account health, platforms, presets | Publish (Compose and Add destination) | once per task |
| Media usage (blocking reasons, resume) | Publish | once on load (and after add destination fails with a duplicate) |
| Set members | Publish | once, after each action, and every 2 s for `publishing` members only |
| Platform options per Draft | Platform card | once on mount; replaced by the PUT response (no re-GET) |
| publish-check per Draft | Platform card | on mount and after each successful autosave or overrides change (drives Ready/Details needed) |
| Creator Info (TikTok Direct Post) | TikTok card | once when Direct Post is chosen or visible; `Retry` on demand; never polled |
| Posts list | Posts (List/History/Calendar/detail) | once, plus the existing polling intervals (2 s while any `publishing`, 15 s while armed posts wait), plus after actions |
| Overview (readiness) | `ProjectLayout` (shared) | existing behaviour, plus `reloadOverview()` when the Posts polling sees a status change or after an action. No independent polling. |
| Account health | Posts (blocked readiness), Post detail | once per Posts mount |
| Attempts | Post detail Activity | when Activity is expanded, and after a state change of that Post |

There is no per-row request in lists. There is no second poller for the same Post: Post
detail reads from `usePostsData`.

## 8. Autosave strategy

`useAutosave<T>(save: (value: T) => Promise<R>, onSaved: (r: R) => void)` (research R-04):

- State `idle | saving | saved | error`, shown as "Saving…", "Saved" and "Couldn't save ·
  Retry" next to the card title (polite live region).
- One request in flight. `schedule(value)` while in flight stores `pending` (only the latest
  value). When the in-flight request settles, a pending value is sent. This gives
  last-write-wins by sequencing, with no AbortController.
- Text fields save on blur, and only if the value changed since the last saved value.
  Radios, checkboxes and selects save on change.
- PUT bodies are the full current option document. After a successful save the backend
  response replaces local values only for fields the user has not touched since (dirty set
  cleared on success).
- `flush(): Promise<boolean>` resolves when nothing is pending or in flight. It returns
  `false` if the last result is an error.
- `AutosaveRegistry` (context in the Publish task and Post detail) keeps the cards'
  `flush`/status. `flushAll()` is used by the CTA validation and by `Finish later`.
- After each success the card refreshes its `publish-check` (one GET) so its state updates.
- Applies to YouTube, Instagram, Threads and TikTok options, and to per-destination content
  overrides in Review (`PATCH` overrides). Telegram has no per-Post options: its card is
  read-only ("Ready · Posts to <channel>", or Blocked with a link to Accounts).

### Finish later (FR-051)

1. `flushAll()`. This sends nothing extra when nothing is pending.
2. If anything is in `error`: a Dialog with "Couldn't save N changes" and the actions
   `Retry` and `Discard and leave`.
3. `navigate(/p/:pid/posts)`. The daily list shows Drafts, and the focus goes to the
   Drafts heading through router state.

No request is made "for" Finish later itself.

## 9. TikTok consent strategy

Research R-05. Concretely:

- **Where shown**:
  - Publish task: inside the TikTok card when mode is Direct Post and the options are
    complete (`fingerprint !== null`).
  - Post detail: inside `ActionDialog` for Publish now, Retry now, Reschedule, Edit schedule
    and Publish automatically on a TikTok Direct Post.
  - Upload to Inbox never shows a declaration; it shows the inbox explanation instead.
- **Local representation**: `accepted: {fingerprint, version} | null` per Post per action.
  It starts `null` on every mount of the card or dialog, whatever the persisted
  `consent.state` is.
- **Invalidation**: derived, not an effect: `isAccepted = accepted?.fingerprint ===
  options.fingerprint && accepted?.version === options.declaration.version`. Any autosaved
  option or caption change produces a new fingerprint from the PUT/GET response, so the box
  unchecks automatically.
- **Recording**: in the orchestration step of that Post, immediately before its action:
  `confirmTikTokConsent(id, accepted.fingerprint, accepted.version)`, then `publishNow` or
  `updatePublication({scheduled_at, auto_publish_enabled: true})` (Schedule, Reschedule, Edit
  schedule) or `{auto_publish_enabled: true}` (Publish automatically).
  `tiktok_consent_stale` means the options changed after the check: the box resets and the
  Post shows "Didn't start · Confirm the TikTok declaration again". The other Posts continue.
- **Validation**: `tiktok_consent_required` from `publish-check` counts as satisfied iff
  `isAccepted`. Otherwise the error summary links to the declaration checkbox.
- **Legacy second checkbox**: the two legacy confirmations (`TikTokPublishOptions` checkbox
  and `PublishNowDialog`) live only in the components being replaced. During migration (§13)
  the old screens keep them untouched until their route switches to the new surface in the
  same block, after which the legacy component is deleted. The new `TikTokDetails` never
  renders the persisting checkbox. Nothing changes in the backend: fingerprint, staleness,
  `arming_problems` and preflight stay as they are (013 FR-025).
- Retry with an uncertain result keeps the existing acknowledgement checkbox
  (`confirm_remote_checked`). That checkbox is a different confirmation, not a second TikTok
  declaration (see C1).

## 10. Partial-failure strategy

| Kind | When | Behaviour |
|---|---|---|
| **Validation failure** | before any write of the action | Nothing runs. `ErrorSummary` (`role=alert`, focused) links to each card/field. Inline errors stay. The CTA stays enabled. |
| **Creation failure** (Continue) | backend 4xx | All-or-nothing (017). Nothing created. Field/destination errors are mapped back to Compose. |
| **Execution failure, Now** | a Post's consent or `publish` call fails | That Post shows "Didn't start · <message>" and stays in its real state (Draft → Review again). The others continue. The aggregate line counts real outcomes. |
| **Runtime failure, Now** | upload fails or ends uncertain | Comes from polling: Failed / Needs review per row. The aggregate is e.g. "2 published · 1 failed", never "Publish failed". |
| **Execution failure, Schedule** | a Post's consent or `PATCH` fails after others succeeded | No rollback, no auto-navigation. Results: "3 scheduled · 1 still a draft". The failed Post stays a Draft in "Still to finish", with its message and the CTA `Schedule 1 post` to retry after fixing it. |
| **Leaving during execution** | navigation | Allowed. The text "Publishing continues in the background. Track it in Posts." is shown. Once the prevalidation passed and the CTA was pressed, SPA navigation does **not** cancel the sequence: no AbortController or unmount cleanup is attached to the start mutations, so the remaining starts are still issued; only the unmounted component stops updating. Posts is where progress is followed. Closing the tab may interrupt requests not yet sent (outside this guarantee; no background worker). |

Sequential execution makes each outcome attributable. Already started Posts are never
undone.

## 11. Responsive strategy

- Breakpoints: `sm <768`, `md 768–1023`, `lg 1024–1279`, `xl ≥1280` (add `xl` to
  `breakpoints.ts` and `tokens.css`).
- `DetailSurface panelFrom`:

  | Surface | `panelFrom` | 1024–1279 |
  |---|---|---|
  | Accounts | `lg` | unchanged |
  | Posts List/History | `lg` | panel |
  | Library | `xl` | Drawer |
  | Calendar | `xl` | Drawer |

  Modality changes (panel vs modal Drawer vs page) are decided in JS (`useMediaQuery`),
  because semantics change. Everything else is CSS.
- Library grid: CSS auto-fill (§3).
- Posts rows: full width at all sizes, one column.
- Calendar: week view at ≥1024 (7 equal columns, compact blocks: time, platform icon, status
  icon + text, truncated title); agenda below 1024 (day headings + list). This is chosen in
  JS because the DOM structure changes.
- Publish: single column `max-width: 720px` at md+. On `sm` it runs as a task: bottom nav
  hidden (`handle.taskMode`). `PageActions` renders a sticky bottom bar with the CTA and
  `Finish later`. The bar reserves `scroll-padding-bottom` so it never covers the focused
  field.
- Details on `sm` are full-screen with Back, and the bottom nav is kept (consultation).
- Touch targets ≥44 px through the existing tokens. No horizontal page scroll is verified at
  375 px.

## 12. Media edit inheritance warning

- **Data**: the `getContentUsage(mid)` already loaded by Media detail now carries `inherits`,
  `display_state` and `consent_covers_caption`. No extra query, no network.
- **When computed**: on every change of the dirty field set while editing (pure function).
  - Affected Posts: `inherits[field] === true` for a changed field, and `display_state`
    not in `published`/`cancelled`.
  - The inline warning shows the count, the destinations (account names) and the states
    (StatusBadge labels).
- **Dialog**: on Save, if any affected Post has a TikTok platform,
  `display_state ∈ {scheduled_automatic, scheduled_paused}`, `consent_covers_caption`, and a
  changed field among `description`/`hashtags` (the caption is built from them; the title is
  not part of TikTok's caption). The Dialog reads: "TikTok won't publish these posts
  automatically until you confirm the TikTok declaration again." Actions: `Save anyway` and
  `Cancel`.
- New 019 drafts have snapshot overrides, so they never count as affected.

## 13. Posts architecture

- `usePostsData(projectId)`: `listPublications` plus polling (§7). It exposes `posts`,
  `reload`, `byId`. `onStatusChange` → `reloadOverview()`.
- `readiness.ts`:
  - `incompleteIds = overview.attention.filter(kind==="incomplete").map(post.id)` with the
    item's `detail`.
  - `blockedAccounts = accountHealth.filter(state !== "ready" && is_active)`.
  - A Post with a `scheduled_*` state within 7 days is in one of three states:
    - `needs_details`: in `incompleteIds`; the summary is its detail, including "Couldn't
      verify requirements".
    - `blocked`: its account is in `blockedAccounts`; the reason is "Reconnect account" or
      "Finish account setup".
    - `ready`: otherwise.
  - No indicator beyond 7 days. Drafts are "not ready" by definition.
- `sections.ts` follows the exact precedence in contracts/ui.md §4:
  - Each Post goes to exactly one section; Needs you is checked first.
  - Needs you sort: rank (`needs_review` 1, `failed` 2, `missed` 3, `needs_action` 4,
    scheduled with problem 6), then the anchor date ascending.
  - Upcoming groups by local day.
  - History groups by month of the anchor (`published_at` / `updated_at` for cancelled).
    It shows the first 30 and adds 30 per `Show more` (`?show=` optional).
- Toolbar:
  - Search over the title, caption, hashtags and account label.
  - `account` select built from the accounts present in the list.
  - Both apply to every view, Calendar included.
- One project banner when `overview.automation.paused` (reuses the 018
  `AutomationPausedBanner`).
- `PostRow` is one `<Link>` with: thumbnail (`content.file_url` image, video poster via
  `MediaPreview` compact) or text icon, title or excerpt, platform/account, anchor date,
  StatusBadge, and a next-action hint for Needs you (from `post-actions.ts` hints, e.g.
  "Retry or reschedule", "Finish in TikTok", "Add 2 details" from the readiness summary).
- Selection: `/posts/:id?<same query>`. The list stays mounted and `PostDetail` is keyed by
  id only, so status updates do not remount it.

## 14. Calendar architecture

- URL `?view=calendar&week=YYYY-MM-DD` (local Monday). `calendar.ts`:
  - `parseWeek(param, today)`: an invalid value gives the current Monday, written back with
    `replace`.
  - `weekDays(monday)`.
  - `formatRange(monday, locale)`.
  - `calendarMoment(post)` (research R-09 anchors).
  - `postsByDay(posts, monday)`: excludes `draft`/`cancelled` and sorts by time.
- Locale: `navigator.language` through `Intl.DateTimeFormat`. The time zone shown is
  `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- Navigation: previous / Today / next change `week` with `navigate` (push, so back works
  across weeks).
- `CalendarWeek` (≥1024): `<section>` per day with `<h3>` and a `<ul>` of compact Links;
  items at the same time stack. `CalendarAgenda` (<1024): day sections with a list. Empty
  week: neutral message plus navigation.
- No `role=grid`, no drag, no slot creation.

## 15. Post detail architecture

`PostDetail` reads `post = byId(postId)` from `usePostsData`; if the Post is missing from
the list, it falls back to `getPublication` once (deep link before the list loads).

1. **Header**: media thumbnail or text icon, title or excerpt, platform/account.
2. **StatusActionPanel**: one sentence plus actions from `post-actions.ts`
   (contracts/ui.md §5), driven by `display_state` plus readiness.
3. **When**: date with time zone, automatic/manual/paused. `Edit schedule` / `Reschedule`
   open the `ActionDialog` (Dialog on md+, Sheet on sm) with a native
   `<input type=datetime-local>` (no custom picker), a readable preview and the
   "AutoPublisher will publish… automatically" text. The paused warning has a link to
   Settings.
4. **Content**:
   - Draft or Scheduled: per-field rows with provenance ("Custom text" / "Uses the media's
     caption") and a single `Edit` that opens an inline editor with Save/Cancel, plus `Use
     the media's caption` (`PATCH` override `null`). Customizing a TikTok armed Post shows the
     consent consequence before saving.
   - Published: `sent-content.ts` maps `latest_attempt.submitted` (research R-08), with the
     fallback note.
5. **Platform details**: the same `PlatformDetails` card as in Publish, with autosave.
   Collapsed when Ready or Published, open when there are problems.
6. **Activity** (Disclosure, collapsed): human events from attempts ("Tue 18:00 · Started
   automatically", "… · Failed: <message>"), then a second Disclosure "Technical details"
   (codes, attempt ids, stages, external ids, checksums).
   **Unexpected `check_result_first`** on a visible Failed (the uncertain attempt belongs to
   another Post of the same Media + account): show "Check the result first."; offer a `Check
   result` link only when that Post is identifiable from `usePostsData` (a `needs_review` Post
   of the same Media + account); otherwise only the message and a pointer to Needs you. Never
   bypass the guard; no new backend.
   **Check result** (Needs review, spec FR-073a): `CheckResultDialog` runs `publish-check`
   (read-only reconcile where supported) and reloads the Post. If the result was resolved, the
   Dialog closes on the determined state (Published, or Failed with R6 actions). If still
   uncertain, it explains what to check on the platform and shows the existing
   acknowledgement ("I checked <platform> and this post was not published"); only when it is
   checked is `Publish again` enabled → `publishNow(id, true)` (TikTok Direct Post also shows
   the single declaration). Reschedule/Move to drafts are never offered while uncertain.
7. **Destructive area**: `Cancel post` opens a Dialog ("You can reactivate it later") →
   `cancelPublication`. `Reactivate` calls `reactivatePublication` with its existing
   semantics, unchanged.

Legacy per-section Save buttons (schedule form, metadata form, per-platform Save) are
removed. Dialog actions and autosave replace them.

## 16. Failed lifecycle change (backend)

Implementation: data-model §3, contracts/api.md §4.

Rules:
- Attempts are preserved.
- `auto_publish_error` is cleared.
- `disarm()` runs before arming.
- Pause is respected (an armed Post shows `scheduled_paused`).
- TikTok arming requires a valid consent through the existing `arming_problems`.
- Duplicates are impossible because FAILED and SCHEDULED are both active statuses.

Regression tests (`backend/tests/test_publications_update.py`, parametrized where possible):
1. FAILED (determined) + `{scheduled_at: future, auto_publish_enabled: true}` → SCHEDULED,
   armed, attempts count unchanged, `auto_publish_error` null, `display_state` automatic.
2. Same with automation paused → `scheduled_paused`.
3. FAILED + `{scheduled_at: null}` (current null) → UNSCHEDULED (draft).
4. FAILED with an uncertain latest attempt → 409 `check_result_first`; status unchanged. Both
   for a future date + arm and for `{scheduled_at: null}` when the current value is already
   `null` (Move to drafts of a Failed Publish now).
5. FAILED + past date → 422; status unchanged.
6. FAILED TikTok Direct Post without a valid consent + arm → 409 `tiktok_consent_required`
   and no change (atomic).
7. FAILED + overrides only → unchanged behaviour (still FAILED).
8. Reactivate behaviour unchanged (an existing test covers it; add nothing unless missing).
9. Uncertain FAILED + `POST /publish {confirm_remote_checked: true}` still starts a new
   attempt (006 FR-041 path preserved; existing ambiguity tests cover it, extend only if
   missing). After that new attempt fails *determined*, `PATCH` reschedule is allowed.

## 17. Published historical content

`sent-content.ts` maps by platform and mode (research R-08):

| Platform | Source | UI |
|---|---|---|
| YouTube | `submitted.title`, `submitted.description` | Title + Description |
| Instagram | `submitted.caption`, `alt_text` | Caption (+ alt text) |
| Threads | `submitted.text`, `alt_text` | Text |
| TikTok Direct Post | `submitted.caption` | Caption |
| TikTok Inbox | — | "You wrote the caption in TikTok." |
| Telegram | only `text_length` | Effective content + "May differ from what was sent." |
| No attempt / legacy | — | Effective content + the same note |

The current effective content, when different, appears under a secondary "Current text"
disclosure.

## 18. Text-only Posts

- `PublishTextPage` renders `PublishTask mode="text"`, using the same reducer, Review,
  platform cards, When, CTA, results and set identity (`/posts/new?posts=`).
- Text mode differences:
  - There is no `MediaSummary`.
  - Compose has a required text plus hashtags.
  - Destinations need the `text` capability (account health). The others are disabled with
    "Needs media".
  - `Continue` → `createTextPublications`. Its overrides are already explicit.
  - Per-destination customization happens only in Review (C3).
- Resume: Post detail `Continue setup` → `/posts/new?posts=<id>`. The Posts Drafts row links
  to the detail. A text "set" is always given by ids; it is never inferred.
- `New post` menu (Posts header): `Publish media…` → Library (prompts the user to pick a
  Media) and `Text post` → `/posts/new`.

## 19. DetailSurface extensions

- Keep the portal and content node unchanged, so crossing breakpoints keeps the state.
- `panelFrom` replaces the hard-coded `MEDIA_LG_UP` for the panel decision. The default is
  `lg`, so Accounts is untouched.
- Own scroll: `.ap-detail-panel` / `.ap-modal--drawer` / `.ap-detail-page` get
  `overflow-y: auto` with a fixed header. The list keeps its own scroll.
- `actions` slot: a sticky footer inside the surface, with `scroll-padding-bottom` on the
  scroll area so the focused element is never covered.
- Focus:
  - On open (panel), focus goes to the heading (`tabIndex=-1`) only when opened by user
    navigation, not on a reload.
  - On close, focus returns to the originating row or card. The list rows hold a
    `data-detail-id`, and the page restores focus after navigating to the parent URL.
  - Drawer and Dialog already return focus through Radix.
- No remount on status: pages key the detail by id only.
- Tests: extend `ui/detail-surface.test.tsx`: `panelFrom="xl"` gives a Drawer at 1100 px and
  a panel at 1300 px; the `actions` slot renders; the Accounts default behaviour is
  unchanged.

## 20. Design system additions

Only `Field`, `ChoiceGroup` (incl. `horizontal` and `variant="switch"`), `PageActions`, the
route `taskMode`, the DetailSurface extensions and the `xl` breakpoint. `ErrorSummary` and
`TikTokDeclaration` are feature components, not primitives. Nothing else: no Stepper, Toast,
Table or DatePicker (native `datetime-local`).

UI UX Pro Max may be consulted for form patterns, long workflows, calendar agenda, content
library grids and sticky actions. Priority: product/spec > accessibility > skill >
aesthetics. Adopted recommendations go into `docs/design-system.md`.

## 21. Accessibility strategy

- Semantics:
  - Lists are `<ul>`; each card or row is a single Link.
  - Calendar uses day sections and lists.
  - Choices use `fieldset`/`legend`.
  - Disclosures use `button[aria-expanded]` (existing `Disclosure`).
- Focus:
  - Details: focus on open and return (§19).
  - Error summary: focused, with links that move focus to the field (`#id` + `focus()`).
  - After Continue: focus on the Review heading.
  - After the CTA: focus on the Results heading.
- Live regions:
  - Autosave status and per-Post results (polite).
  - Error summary (`role=alert`).
- Status is always shown as icon + text (`StatusBadge`).
- Loading uses `Skeleton` + `aria-busy`. Errors use `ErrorState` + Retry.
- Destructive actions (remove destination, cancel post, discard edits) use a Dialog.
- Sticky bars never cover the focus (`scroll-padding`). Motion respects
  `prefers-reduced-motion` (tokens already do).
- Contrast AA with 018 tokens.

## 22. Legacy migration and removal

Order of blocks. Each block switches its route to the new surface and deletes the replaced
component in the same block, so there are never two complete implementations of one surface.

1. **Foundations**:
   - `Field`, `ChoiceGroup`, `PageActions`, `xl`, DetailSurface extensions, `taskMode`.
   - `useAutosave` + registry.
   - `PlatformDetails` cards (adapted from `*PublishOptions`; option components'
     tests migrate to the new cards).
2. **Backend**: usage read-model extensions (+ tests in `test_asset_usage.py`) and the
   FAILED transition (+ tests in `test_publications_update.py`).
3. **Library + Media detail**:
   - Replaces `ContentLibrary`, `ContentDetail`, `AssetUsage`, `ContentImport`, `AssetFile`.
   - The "Publish…" action temporarily points to the new route (stub until block 4) or to
     the old `Distribute` behind the new route.
   - Migrate tests from `ContentLibrary.test`, `ContentDetail.test`, `AssetUsage.test` and
     `AssetFile.test`.
4. **Publish task (media)**: replaces `Distribute` (presets logic extracted first into
   `PresetsDialog` + `snapshot.ts`). Migrate the scenarios of `Distribute.test` (create,
   atomic error, customize, presets, PUBLISHED not blocking). Delete `Distribute`.
5. **Posts List/History + Post detail**:
   - Replaces `PublicationQueue`, `PublicationDetail`, `PublicationControls`,
     `PublishNowDialog`, `AutoPublishConsent`, `AutoPublishBadge` and `useLivePublication`.
   - The legacy TikTok double confirmation disappears here.
   - `PublicationAttempts` becomes `Activity`.
   - Migrate the relevant scenarios of `PublicationQueue.test`, `PublicationDetail.test`,
     `PublicationAttempts.test` and `AutoPublishBadge.test`.
6. **Text posts**: replaces `TextPublicationCreate` (its test migrates to the text Publish
   task).
7. **Calendar**.
8. **Cleanup**:
   - Remove the legacy CSS of these surfaces from `index.css`.
   - Remove unused helpers in `utils.ts`, such as `PUBLICATION_STATUS_LABELS` usage and
     `publicationStatusLabel`, if unused.
   - Update `docs/design-system.md` and the README.

"Inline fake dialogs" (`section role="dialog"` in `PublishNowDialog` and others) disappear
with their components and are replaced by Radix `Dialog`/`Sheet`.

## 23. Testing strategy

CLAUDE.md policy:
- During implementation: targeted tests of the modified block only.
- Before the PR, once: the pending targeted tests, lint, format, mypy, typecheck, the
  frontend build and `git diff --check`.
- Full pytest/Vitest run only in PR CI.

Representative tests (no combinatorial matrices; parametrize where natural):

| Area | Test (file) |
|---|---|
| Publish state machine | `publish/usePublishTask.test.tsx`: compose→creating→task; creation 4xx keeps input; partition by state |
| Snapshot | `publish/snapshot.test.ts`: explicit description/hashtags always; title only for YouTube; empty values explicit; customization wins |
| Resume | Media with 2 drafts, no `posts` → Review + URL rewritten; provenance labels ("Custom text" / "Uses the media's caption") |
| Mixed set | `?posts=` with 1 published + 1 failed + 1 draft → Results + "Still to finish · 1"; invalid/foreign id dropped with notice |
| Destinations editing | re-add without reload reactivates exactly the removed id; after reload a new Draft (never a historical Cancelled); `Add to this task` adds a Draft outside the set without writes |
| Autosave | `platform/useAutosave.test.ts`: coalescing, ordering, error→retry, flush; one card integration (YouTube) |
| TikTok declaration | `platform/TikTokDetails.test.tsx` + orchestration: unchecked on mount despite a valid persisted consent; fingerprint change unchecks; consent call precedes publish; stale → "Didn't start"; no second confirmation |
| Validation before start | one Draft with problems → no publish/patch calls; summary focused with links |
| Partial Publish | 3 drafts, 2nd `publish` rejects → 1st and 3rd start; aggregate counts; unmount after the 1st start still issues the remaining starts |
| Partial Schedule | 4 drafts, 4th `PATCH` rejects → "3 scheduled · 1 still a draft"; no navigation; retry CTA for 1 |
| Finish later | pending autosave flushed; failed save → Dialog; no extra request; navigates to Posts |
| Posts grouping | `posts/sections.test.ts` (parametrized): each display_state to one section; Missed in Needs you; incomplete/blocked scheduled in Needs you; ordering |
| Readiness | `posts/readiness.test.ts`: incomplete id, blocked account, ready, >7 days none |
| Failed reschedule (FE) | Post detail Failed → Reschedule calls PATCH with the arm flag; Needs review → only Check result; dialog reconciles (resolved → determined state), else Publish again stays disabled until the acknowledgement and then calls publish with `confirm_remote_checked: true` |
| Failed reschedule (BE) | §16 list |
| Usage read-model (BE) | `test_asset_usage.py`: counts per display state incl. missed (armed overdue and manual past), next_scheduled_at, cancelled_count, `inherits`, `consent_covers_caption`; query count stays constant (no N+1) |
| Calendar anchoring | `posts/calendar.test.ts` (parametrized): published uses published_at despite an old scheduled_at; publishing/failed manual vs scheduled; needs_action finished_at; week parse/invalid |
| DetailSurface | `ui/detail-surface.test.tsx` (§19) |
| Text-post resume | `/posts/new?posts=<id>` → Review of that draft; Continue uses text endpoint |
| Routes | `routes.test.tsx`: new routes resolve; taskMode hides bottom nav on sm; not found for foreign media |

Existing tests of untouched features (Accounts, Home, Settings, connection panels) are not
re-run locally except `detail-surface.test.tsx` (shared component).

## 24. Security and privacy

- `?posts=` contains local numeric ids, the same exposure as the existing `/posts/:id`. They
  are validated against the project and Media and give no access beyond the existing API.
- `submitted` payloads are already "non-sensitive" by contract (`PublicationAttempt`).
  Verified per publisher: no tokens, upload URLs or publish ids. Telegram `random_id`,
  channel ids and user ids are shown only under "Technical details".
- Creator Info: the avatar URL is a signed short-lived URL. It is displayed and never stored
  or logged (as today).
- Error messages: only the backend's safe `message` is shown. Codes appear only in technical
  details. No filesystem paths in normal UI (file details show the filename, not the path).
- Platform option payloads contain no secrets.
- No new logging.

## 25. Performance

- Library: one `listContents` (now 3 aggregate queries) with no per-card requests. Client
  search and filter is O(n) per keystroke, which is fine at hundreds of items.
- Posts: one `listPublications` (existing, batched attempts). History and Calendar are
  derived client-side. Rendering is capped by History's `Show more`.
- Polling: one list poller per Posts page, one set poller in Publish (`publishing` ids only).
  No overview polling.
- `local_check`: only the overview, as today. Posts adds none.
- Publish `publish-check` per Draft (N ≤ accounts): it may run TikTok/YouTube local checks
  (video metadata reads). It happens only on mount and after saves, and is accepted.
- Creator Info: a network call per TikTok Direct Post card mount and Retry only.
- Options GETs: one per Draft card. This is N requests by design; no batch endpoint is
  justified at this N.
- Clear N+1 avoided: Media cards (usage aggregates), usage rows (attempts and TikTok options
  in batch), Post rows (no per-row requests).

## 26. Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Client orchestration interrupted mid-way (tab closed) | Each Post is independent and stays in its real state; `?posts=` rebuilds; unstarted Posts remain Drafts. |
| Autosave races | Sequenced single-flight + pending coalescing; flush before CTA/Finish later. |
| TikTok fingerprint drift between check and action | Backend recomputes; `tiktok_consent_stale` → per-Post "Didn't start", others continue. |
| `publish-check` reconciliation on a FAILED member (network read) | Only for Failed members in a mixed set; Results rows do not run publish-check (only Drafts do). |
| Readiness for posts folded into `reconnect` | Derived from account health (R-06). |
| Large migration | Block-by-block route switch with deletion in the same block; tests migrate with each block. |
| Calendar week density at 1024 px | Compact blocks, truncated titles, agenda below 1024. |

## 27. Exact feature boundary

In scope: everything in spec FR-001…FR-095, the backend changes in §4, and §16 tests.

Out of scope (unchanged):
- Feature 020 (deployment, auth, LAN, HTTPS, PWA, push, background service, backups).
- Republish.
- An editable calendar.
- Bulk management.
- Backend pagination.
- Library sorting.
- A thumbnail pipeline.
- Deleting Posts.
- Exhaustive readiness.
- A batch entity or endpoint.
- Changes to the scheduler, publishers, overview or Reactivate.
- New migrations.

## Contradictions and decisions requiring attention

| # | Type | Finding | Plan position |
|---|---|---|---|
| C1 | **Resolved** (spec FR-073a) | Needs review vs 006 FR-041 manual retry after acknowledgement. | While uncertain: direct Retry, Reschedule and Move to drafts are blocked ("Check the result first."); primary action `Check result`. The `CheckResultDialog` keeps the 006 path: `publish-check` (read-only reconcile where the platform allows) → if resolved, the Post shows its determined state (Published, or Failed with R6 actions); if still uncertain, explicit acknowledgement → `Publish again` = `POST /publish {confirm_remote_checked: true}`. No new lifecycle. |
| C2 | Constraint | Telegram attempts store only `text_length`; TikTok Inbox sends no caption. FR-074 "content actually sent" cannot be shown for them. | Fallback to effective content + "May differ from what was sent" (Telegram); "You wrote the caption in TikTok" (Inbox). No new persistence (spec allows fallback). |
| C3 | Plan decision | `POST text-publications` accepts one common text, no per-target overrides. | Text Compose has no per-destination Customize; customization happens in Review (`PATCH` per Post). The snapshot is still explicit. A text Compose interrupted by reload is lost (Compose is local by spec). |
| C4 | Plan decision | The overview folds posts with only connection problems into the account `reconnect` item (no post id). | Posts derives "Blocked" from account health for Scheduled ≤7 days. No backend change. |
| C5 | Plan decision | `needs_action` anchor: `delivered_at` exists only in `GET tiktok-delivery` (per Post). | Use `latest_attempt.finished_at` (the delivery attempt finishing = delivered to the inbox) with an `updated_at` fallback. No per-Post requests. |
| C6 | Plan decision | `TEXT_POST_PLATFORMS` (frontend constant) disagrees with its own comment (Threads only vs threads+telegram). | Text destinations use account health `capabilities.includes("text")` (backend truth). The constant is removed with `TextPublicationCreate`. |

## Project Structure

### Documentation (this feature)

```text
specs/019-core-workflows-ux/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md
│   └── ui.md
├── checklists/requirements.md
└── tasks.md            # created by /speckit-tasks (not by this command)
```

### Source Code (repository root)

```text
backend/app/{schemas.py, asset_library.py, contents.py, publications.py}
backend/tests/{test_asset_usage.py, test_publications_update.py}
frontend/src/{routes.tsx, shell/AppShell.tsx, ui/*, components/platform/*,
              pages/{LibraryPage.tsx, PostsPage.tsx}, pages/{library,publish,posts}/*}
docs/design-system.md, README.md
```

**Structure Decision**: the existing web app (`backend/` + `frontend/`). New frontend code is
grouped by page (`pages/library`, `pages/publish`, `pages/posts`), with platform cards shared
under `components/platform`.

## Complexity Tracking

No constitution violations to justify.
