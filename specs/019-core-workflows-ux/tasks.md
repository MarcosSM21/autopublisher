---

description: "Task list for Feature 019 — Core Workflows UX Redesign"
---

# Tasks: Core Workflows UX Redesign

**Input**: Design documents from `/specs/019-core-workflows-ux/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/api.md](contracts/api.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md)

**Tests**: requested by the spec and plan §23. Use a **targeted, representative and
parametrized** set; do not build platform × state matrices. During implementation run only
the tests of the modified block (`cd backend && uv run pytest <files> -q` /
`cd frontend && npx vitest run <paths>`). A test that already passed is not re-run unless
its code changed. Do **not** run the full pytest or Vitest suite locally: full suites run
only in PR CI. Static checks run once, in Phase 13.

**Organization**: blocks follow the order of real dependencies. Each block leaves the app
usable, and when a surface switches to the new implementation its legacy component is
deleted **in the same block**. Stories (spec.md):
- US1 Publish Media (P1)
- US2 Resume / Finish later (P1)
- US3 Posts (P1)
- US4 Post detail / recovery (P1)
- US5 Library + Media detail (P2)
- US6 Calendar (P2)
- US7 Text post (P2)

US5 is implemented before US1 because Publish starts from Media detail. Accessibility and
responsive work is done inside each block; Phase 13 holds only a short cross-cutting review.

**Task format**: `- [ ] ID [P?] [Story?] Description (files)`, followed by the sub-bullets
**Deps** (blocking tasks), **Tests** (targeted) and **Done** (acceptance criterion).

**Feature boundary**:
- Nothing from Feature 020.
- No Republish, editable calendar, bulk management, backend pagination, Library sorting,
  thumbnail pipeline or Post deletion.
- No change to Reactivate, the scheduler, the publishers or the overview.
- No migrations.
- R6 is the only lifecycle change.

**External validation**: no STOP gate. The backend publishers do not change and every new
behaviour is covered with contracts, fakes and existing mocks (`FakeApi`,
`backend/tests/fakes*.py`).

---

## Phase 1: Shared foundations (design system additions)

**Purpose**: the only primitives and extensions approved in plan §20/§19. They are a
prerequisite of every new surface.

- [X] T001 Add the `xl = 1280` breakpoint (`BREAKPOINT_XL`, `MEDIA_XL_UP`) to `frontend/src/ui/breakpoints.ts` and `--bp-xl` to `frontend/src/ui/tokens.css`; document it in `docs/design-system.md` (breakpoints section).
  - **Deps**: —
  - **Tests**: none (constant).
  - **Done**: the constants are exported and the docs list `sm/md/lg/xl`.
- [X] T002 [P] Create `frontend/src/ui/Field.tsx`: label, hint, required marker and inline error, with `aria-describedby`/`aria-invalid`; the input is passed as children, plus an `id` helper. Add its styles to `frontend/src/ui/ui.css`.
  - **Deps**: —
  - **Tests**: `frontend/src/ui/field-choice.test.tsx` covers the accessible name, the description and the invalid state.
  - **Done**: an input inside `Field` exposes its label, hint and error to assistive technology.
- [X] T003 [P] Create `frontend/src/ui/ChoiceGroup.tsx`: a radio group built on `fieldset`/`legend`, with `orientation="vertical|horizontal"` and `variant="switch"` (view switch, e.g. List | Calendar). Arrow keys follow native radio behaviour, targets are ≥44 px and focus is visible; styles go in `ui.css`.
  - **Deps**: —
  - **Tests**: `frontend/src/ui/field-choice.test.tsx` covers the legend, the selection with keyboard and click, and `onChange` in both variants.
  - **Done**: the same component serves platform choices and the view switch.
- [X] T004 [P] Create `frontend/src/ui/PageActions.tsx` (page actions):
  - On md+ the actions stay inline in the header.
  - On `sm` they render as a sticky bottom bar with the primary action and at most one secondary (no generic overflow menu: add one only if a concrete surface needs it).
  - The bar adds `scroll-padding-bottom` to the scroll container so it never covers the focused element.
  - Styles go in `ui.css`.
  - **Deps**: T001
  - **Tests**: `frontend/src/ui/page-actions.test.tsx` covers the primary and secondary actions inline on md+ and in the sticky bar on `sm` (mocked `matchMedia`).
  - **Done**: Publish and the details can use it.
- [X] T005 Extend `frontend/src/ui/DetailSurface.tsx` and its CSS:
  - A `panelFrom?: "lg" | "xl"` prop (default `lg`).
  - An `actions?: ReactNode` sticky footer.
  - Its own scroll area with a fixed header.
  - Focus on the heading (`tabIndex=-1`) when it opens by user navigation.
  - Keep the persistent portal: no remount across breakpoints.
  - **Deps**: T001
  - **Tests**: extend `frontend/src/ui/detail-surface.test.tsx`:
    - `panelFrom="xl"` gives a Drawer at 1100 px and a panel at 1300 px;
    - `actions` renders;
    - the default behaviour (Accounts) is unchanged;
    - the content keeps its state when the breakpoint changes.
  - **Done**: Accounts works the same and the new props are available.
- [X] T006 Add `handle: { taskMode: true }` support to `frontend/src/shell/AppShell.tsx`: `useMatches()` detects it and hides the bottom navigation only on `sm`, keeping the TopBar. Add the CSS in `frontend/src/shell/shell.css`.
  - **Deps**: —
  - **Tests**: `frontend/src/shell/shell.test.tsx` uses a test memory route with `taskMode` and checks that the bottom nav is absent on `sm`, present without `taskMode`, and that the rail/sidebar is unchanged on md/lg.
  - **Done**: routes can declare task mode.

**Checkpoint**: primitives available; Accounts without regression (`detail-surface.test.tsx` green).

---

## Phase 2: Backend — usage read-model and Failed lifecycle (R6)

**Purpose**: backend contracts before their consumers (data-model §1–3, contracts/api.md §3–4).

- [X] T007 Move `requires_remote_check` without changes from `backend/app/publishing.py` to `backend/app/post_state.py` (next to `needs_manual_review`). Re-export it from `publishing` for its current callers. This avoids an import cycle with `publications.py`.
  - **Deps**: —
  - **Tests**: `uv run pytest tests/test_publish_ambiguity.py tests/test_post_display_state.py -q`.
  - **Done**: same behaviour, mypy clean on the touched files.
- [X] T008 Extend `ContentUsageRead` with `draft_count`, `attention_count`, `upcoming_count`, `next_scheduled_at` and `cancelled_count`, and `AssetPublicationRead` with `display_state`, `inherits` (new `FieldInheritanceRead` with `title/description/hashtags: bool`) and `consent_covers_caption`, all with compatible defaults, in `backend/app/schemas.py`.
  - **Deps**: —
  - **Tests**: covered by T011.
  - **Done**: the schemas match data-model §1–2.
- [X] T009 Extend `usage_by_content(session, project_id, ids, *, now, paused)` in `backend/app/asset_library.py`:
  - Add **one** extra query per project over non-history Posts, `(content_id, status, auto_publish_enabled, scheduled_at)`.
  - Evaluate `post_state.post_display_state` with the response's single `now` and `paused` to compute the new counts:
    - attention = `failed`, `needs_review`, `needs_action`, `missed`;
    - upcoming = `publishing` and `scheduled_*`;
    - `next_scheduled_at` = the earliest `scheduled_*`.
  - Pass `now` (`ClockDep`) and `paused` (`is_paused`) from `list_contents` / `content_read` in `backend/app/contents.py` and their endpoints.
  - **Deps**: T008
  - **Tests**: T011.
  - **Done**: Library receives the counts without new per-Media queries.
- [X] T010 In `get_content_usage` (`backend/app/asset_library.py`):
  - Compute `display_state` per row from the latest attempt already loaded.
  - Compute `inherits` (`*_override is None`).
  - Compute `consent_covers_caption` (TikTok, `mode == DIRECT_POST`, `consent_fingerprint` not null) with **one** query over `TikTokPublicationOptions` for the TikTok ids of the response.
  - No network and no hashing.
  - **Deps**: T008, T009
  - **Tests**: T011.
  - **Done**: contracts/api.md §3 is satisfied.
- [X] T011 Add tests to `backend/tests/test_asset_usage.py` (parametrized):
  - counts per display state, including `missed` both armed-overdue and manual-past;
  - `needs_review` counts as attention;
  - `next_scheduled_at`, `cancelled_count`, and "Not used yet" (`publication_count == cancelled_count`);
  - `display_state` per row;
  - `inherits` with snapshot vs inherited values;
  - `consent_covers_caption` for TikTok Direct Post with consent, Inbox, and no consent;
  - the number of queries stays constant with N Media (no N+1).
  - **Deps**: T009, T010
  - **Tests**: `uv run pytest tests/test_asset_usage.py tests/test_contents_api.py -q`.
  - **Done**: green.
- [X] T012 Implement the R6 transition in `backend/app/publications.py`:
  - `ensure_editable` receives the `session` so it can call `requires_remote_check`. For `FAILED`, the **mere presence** of `scheduled_at` in the PATCH body counts as a scheduling change for the guard, even when `old == new == null` (Move to drafts of a Failed Publish now). Arming also counts. If `requires_remote_check` is true, any such explicit Reschedule or Move to drafts raises `ConflictError("check_result_first", "Check the result first.")` with field `scheduled_at`; nothing is changed.
  - `update_publication`, for `FAILED` with `scheduled_at` in the fields: always transition, even if the value is the same.
    - A non-null value goes through `ensure_future` + `ensure_can_prepare` → `SCHEDULED`.
    - `null` → `UNSCHEDULED`.
    - Then `disarm()`, then `clear_auto_publish_error()`, then the existing arming path (`_set_consent` + `_arming_problems`), all in the same request.
  - Attempts stay intact. Reactivate does not change.
  - **Deps**: T007
  - **Tests**: T013.
  - **Done**: contracts/api.md §4 is satisfied.
- [X] T013 Add regression tests to `backend/tests/test_publications_update.py` (plan §16 cases 1–9, parametrized where they share setup):
  1. Failed determined + future date + arm → `SCHEDULED` armed; attempts kept; error cleared.
  2. The same with automation paused → `scheduled_paused`.
  3. Failed + `scheduled_at: null` → `UNSCHEDULED`.
  4. Uncertain → 409 `check_result_first`, nothing changes; parametrized over `{scheduled_at: <future>, auto_publish_enabled: true}` **and** `{scheduled_at: null}` on a Failed whose `scheduled_at` is already `null` (explicit H1 regression).
  5. Past date → 422, nothing changes.
  6. TikTok Direct Post without consent + arm → 409 `tiktok_consent_required`, atomic.
  7. Overrides only → still `FAILED`.
  8. Reactivate unchanged: confirm it with the existing tests and add a test only if one is missing.
  9. `POST /publish {confirm_remote_checked: true}` on an uncertain Post still starts a new attempt. If that attempt fails determined, `PATCH` reschedule is allowed.
  - **Deps**: T012
  - **Tests**: `uv run pytest tests/test_publications_update.py tests/test_publications_lifecycle.py tests/test_publish_ambiguity.py -q`.
  - **Done**: green.
- [X] T014 Update the frontend contract:
  - `frontend/src/types.ts`: `ContentUsage` and `AssetPublication` with the new fields.
  - `frontend/src/api.ts`: no new function; keep the PATCH documentation in sync.
  - `frontend/src/test-fake-api.ts`: new usage fields derived from the fake's state; FAILED transition and `check_result_first`; `confirm_remote_checked`.
  - **Deps**: T008–T012
  - **Tests**: `npx vitest run src/api.test.ts` (only if it touches the parsing).
  - **Done**: typecheck clean on these files; the FakeApi reproduces contracts/api.md §3–4.

**Checkpoint**: contracts ready; backend tests of the block green.

---

## Phase 3: Shared platform details (autosave + cards + TikTok declaration)

**Purpose**: plan §8–9. Publish Review (US1) and Post detail (US4) use the same cards. The
legacy `*PublishOptions` stay **only** as consumers of the legacy screens until those are
deleted (T042 and T063). No new screen uses them.

- [X] T015 Create `frontend/src/components/platform/useAutosave.ts` and `AutosaveRegistry.tsx` (research R-04):
  - one request in flight, with `pending` coalesced to the latest value;
  - states `idle|saving|saved|error`, plus `retry()` and `flush(): Promise<boolean>`;
  - the registry context exposes `flushAll()` and `hasErrors`;
  - text saves on blur only if it changed; choices save on change; no AbortController.
  - **Deps**: —
  - **Tests**: `frontend/src/components/platform/useAutosave.test.ts`:
    - two changes during the flight → one later request with the last value, in order;
    - a stale response does not overwrite a later edit;
    - error → `retry()` resends the last value;
    - `flush()` waits and returns false on error;
    - `flushAll()` covers several cards.
  - **Done**: green.
- [X] T016 [P] Create `frontend/src/components/platform/platform-state.ts`: map `PublishCheck.problems` + options to `Ready | Details needed | Blocked | Checking` and to a human summary ("TikTok needs 3 details: Privacy, AI-generated content and declaration.").
  - Treat `tiktok_consent_required` as satisfied when the local declaration is accepted (input parameter).
  - Connection problems (`reconnect_required`, inactive, no channel) → Blocked with an action link.
  - **Deps**: —
  - **Tests**: `platform-state.test.ts` parametrized per platform with a representative case: Ready, details, blocked, consent pending vs accepted.
  - **Done**: green.
- [X] T017 Create `frontend/src/components/platform/PlatformDetails.tsx` (card + dispatcher by platform and mode):
  - The header shows the platform, the account, the human state (`StatusBadge`-style icon + text) and the autosave line ("Saving…", "Saved", "Couldn't save · Retry") in a polite live region.
  - Ready is collapsed and Details needed is open (`Disclosure`). Required fields are visible; the rest go under `More options`. Checking shows a `Skeleton` + `aria-busy`.
  - After every successful save, refresh `getPublishCheck` (one GET) and register the card in `AutosaveRegistry`.
  - **Deps**: T015, T016, T002, T003
  - **Tests**: covered by T018–T022.
  - **Done**: the card renders its states and calls the platform component.
- [X] T018 [P] Create `frontend/src/components/platform/YouTubeDetails.tsx`, adapting the fields of `YouTubePublishOptions.tsx` (reuse `YesNo`):
  - Required fields: "Made for kids?" and "Altered or synthetic content?".
  - `More options`: privacy and notify subscribers.
  - Autosave on change, with the full PUT body. No Save button.
  - **Deps**: T017
  - **Tests**: `YouTubeDetails.test.tsx` covers saving on change, the error → Retry path, and the state moving to Ready after saving.
  - **Done**: green.
- [X] T019 [P] Create `frontend/src/components/platform/InstagramDetails.tsx`, adapting `InstagramPublishOptions.tsx`:
  - Required: "AI-generated content?".
  - Share to feed for Reels.
  - Alt text for images, saved on blur.
  - **Deps**: T017
  - **Tests**: `InstagramDetails.test.tsx` covers the required field plus alt text saved on blur.
  - **Done**: green.
- [X] T020 [P] Create `frontend/src/components/platform/ThreadsDetails.tsx`: optional alt text (on blur), adapted from `ThreadsPublishOptions.tsx`. Create `TelegramDetails.tsx`, read-only: "Ready · Posts to <channel>", or Blocked "Choose a channel" with a link to the account.
  - **Deps**: T017
  - **Tests**: `ThreadsTelegramDetails.test.tsx` (one case each).
  - **Done**: green.
- [X] T021 Create `frontend/src/components/platform/tiktok-declaration.ts` and `TikTokDeclaration.tsx` (research R-05):
  - `accepted: {fingerprint, version} | null`, starting at `null` on every mount whatever the persisted `consent.state`;
  - `isAccepted` is derived from the current `options.fingerprint`/`declaration.version`, so it unchecks itself when they change;
  - the official text with its links and one checkbox; it is never persisted on check.
  - **Deps**: —
  - **Tests**: `tiktok-declaration.test.tsx` covers: unchecked with a valid persisted consent; checked → accepted; a new fingerprint unchecks it; a new declaration version unchecks it.
  - **Done**: green.
- [X] T022 Create `frontend/src/components/platform/TikTokDetails.tsx`, adapting `TikTokPublishOptions.tsx` **without** its persisting consent checkbox:
  - First "How should this reach TikTok?" (`ChoiceGroup`: `Post directly` / `Send to my TikTok inbox`), using `modes[...].available/reason` (permission errors shown with the reconnect reason).
  - Inbox: the explanation "You'll get a TikTok inbox notification to finish the post." and Ready when it is available.
  - Direct Post: read Creator Info once when the card opens (loading skeleton, error + `Retry` + `Send to inbox instead`). Privacy has no default and is limited to `allowed_privacy_levels`; if only `SELF_ONLY` is allowed, say so clearly. Interactions are off by default; commercial content and AI-generated follow the 013 rules.
  - Autosave, and the slot for `TikTokDeclaration` (state lifted to the owner of the action).
  - **Deps**: T017, T021
  - **Tests**: `TikTokDetails.test.tsx` covers:
    - choosing the mode;
    - Creator Info failure → Retry and `Send to inbox instead`;
    - only `SELF_ONLY` → clear message;
    - an unavailable mode with its reason;
    - no persisting consent call is ever made from the card.
  - **Done**: green.

**Checkpoint**: cards usable in isolation; legacy screens unchanged.

---

## Phase 4: US5 — Library + Media detail (Priority: P2, implemented first)

**Goal**: find, import and understand the use of each Media; Media detail in `DetailSurface`.

**Independent Test**: quickstart journey E plus spec US5 scenarios 1–11.

- [X] T023 [P] [US5] Create `frontend/src/pages/library/usage-indicator.ts` (one indicator by priority: Needs attention > Scheduled/Publishing > Drafts > Published > Not used yet, data-model §1) and `library-filters.ts`:
  - search over title, filename, description and hashtags;
  - filters All, Images, Videos and Not used yet;
  - pure functions over local state (no URL sync for search or filters).
  - **Deps**: T014
  - **Tests**: `library-helpers.test.ts` (parametrized).
  - **Done**: green.
- [X] T024 [US5] Rewrite `frontend/src/pages/LibraryPage.tsx` as the container, with `frontend/src/pages/library/{LibraryToolbar,MediaGrid,MediaCard}.tsx` and `library.css`:
  - The header shows `Library`, the Media count, search, `Import media` and the filters (`ChoiceGroup` horizontal). Search and filters are local React state of the container (not in the URL).
  - The grid is a `<ul>` with `repeat(auto-fill, minmax(…))`. Each card is a single `<Link>` with preview (`MediaPreview`), duration, title or filename and the indicator. The selected card gets `aria-current="true"` and a strong outline.
  - Selection opens `MediaDetail` in `DetailSurface panelFrom="xl"`; the grid stays mounted (search, filter and scroll kept).
  - Not found is unchanged.
  - **Deps**: T005, T023
  - **Tests**: `frontend/src/pages/library/library.test.tsx`:
    - search by hashtag;
    - the Not used yet filter;
    - opening and closing the detail keeps the search and filter;
    - `aria-current` on the selected card;
    - the detail is not rendered under the grid.
  - **Done**: green.
- [X] T025 [US5] Create `frontend/src/pages/library/ImportPanel.tsx` and `LibraryDropzone.tsx` from the logic of `ContentImport.tsx`:
  - `Import media` opens the file picker directly (hidden `input[type=file][multiple]`);
  - drag and drop on the page from md up;
  - a dismissable inline panel with progress, the aggregate summary and per-file details;
  - empty Library → `EmptyState` with a large dropzone and a single primary import action, not dependent on drag and drop on `sm`;
  - reload the list after importing.
  - **Deps**: T024
  - **Tests**: `library.test.tsx` covers an import of 2 files with 1 rejected (aggregate + detail) and the empty state with one primary action.
  - **Done**: green.
- [X] T026 [US5] Create `frontend/src/pages/library/MediaDetail.tsx`:
  - Order: preview → identity (title or filename, type, duration) → primary action → Content → Usage → File details.
  - Primary action: `Publish…`, or `Continue publishing · N drafts` with the drafts' platforms, as a link to `/p/:pid/library/:mid/publish`. It is disabled with its reason visible when the project is inactive or the file is not available.
  - Sticky actions on `sm` through `DetailSurface actions`.
  - Register the route `library/:mediaId/publish` (declared before `library/:mediaId?`, with `handle.taskMode`) in `frontend/src/routes.tsx`. **Temporarily** it mounts the existing `Distribute` component inside a minimal page with `Back to media`, until T042 replaces it. This is the only legacy entry point to creation.
  - **Deps**: T024, T006
  - **Tests**: `library.test.tsx` covers:
    - the action label with 0 and with 2 drafts;
    - disabled with its reason when the project is inactive;
    - the `/publish` deep link resolves (not found for a Media of another project).
  - **Done**: green.
- [X] T027 [US5] Create `frontend/src/pages/library/MediaContentEditor.tsx` and `InheritanceWarning.tsx` (plan §12):
  - One block, Edit → Save/Cancel, built with `Field`.
  - A pure function computes the affected Posts from `inherits` and `display_state` (Published and Cancelled excluded). The inline warning shows the count, the destinations and the states.
  - On Save, if a TikTok `scheduled_automatic|paused` Post with `consent_covers_caption` is affected and description or hashtags changed, a `Dialog` with `Save anyway` / `Cancel` asks for confirmation.
  - **Deps**: T026
  - **Tests**: `media-content.test.tsx` covers:
    - a warning with 2 inheriting Posts and 1 snapshot Post not counted;
    - Published not counted;
    - the TikTok dialog appears only for a caption change, not for a title change;
    - Cancel does not save.
  - **Done**: green.
- [X] T028 [US5] Create `frontend/src/pages/library/MediaUsage.tsx` and `FileDetails.tsx`:
  - Usage groups the rows by `display_state` into Needs you, Upcoming, Drafts and Published, plus a Cancelled count. Each row is a `<Link>` to `/p/:pid/posts/:id` with a `StatusBadge`. Published shows the last 3 plus `Show all`.
  - FileDetails is a `Disclosure` adapted from `AssetFile.tsx` (filename, format, dimensions, duration, size, published file/version, metadata status, inspect/remove metadata, checksums at the end).
  - **Deps**: T026
  - **Tests**: `media-usage.test.tsx` covers the grouping by display state including missed, the Show all button and the link to the Post. Migrate the relevant cases from `AssetFile.test.tsx` to `FileDetails.test.tsx`.
  - **Done**: green.
- [X] T029 [US5] Delete `ContentLibrary.tsx`, `ContentDetail.tsx`, `AssetUsage.tsx`, `ContentImport.tsx`, `AssetFile.tsx` and their tests (`ContentLibrary.test.tsx`, `ContentDetail.test.tsx`, `AssetUsage.test.tsx`, `AssetFile.test.tsx`) once their scenarios have been migrated in T024–T028. Remove the legacy CSS of those components from `frontend/src/index.css`. Adapt the Library steps of `frontend/src/onboarding.test.tsx` and `frontend/src/routes.test.tsx`.
  - **Deps**: T024–T028
  - **Tests**: `npx vitest run src/pages/library src/onboarding.test.tsx src/routes.test.tsx`.
  - **Done**: no import of the deleted components; green.

**Checkpoint**: new Library usable at 375/768/1024/1280; Publish still runs on legacy `Distribute` under the new route.

---

## Phase 5: US1 — Publish foundation, Publish set and Compose (Priority: P1) 🎯 MVP

**Goal**: own route, a URL-stable set, Compose with explicit snapshot, Continue → Review with
drafts. `Distribute` disappears.

**Independent Test**: spec US1 scenarios 1–7; Compose creates nothing; `?posts=` survives
reload.

- [X] T030 [US1] Create `frontend/src/pages/publish/publish-set.ts` (contracts/ui.md §2):
  - `parsePostsParam`: `parseId` per item, order kept, first occurrence kept, maximum 50.
  - `serializePostsParam`.
  - `validateMembers(posts, {projectId, mode, mediaId})`: same project; in media mode `content_id === mediaId`; in text mode `content_id === null`.
  - `partition(members)`: `draft` → review, everything else → results.
  - **Deps**: —
  - **Tests**: `publish-set.test.ts` (parametrized) covers invalid ids, duplicates, order, a foreign project, another Media, a text Post in media mode, and a mixed partition with draft, scheduled, publishing, published, failed, needs_review and needs_action.
  - **Done**: green.
- [X] T031 [US1] Create `frontend/src/pages/publish/usePublishTask.ts` (a `useReducer`, plan §5):
  - Phases `loading | composing | creating | task`. The Compose state holds `selected`, `common`, `custom` (dirty fields only) and `presetNotice`. The task state holds the members partitioned into review and results.
  - Actions for the transitions in plan §5. The executions are added in Phase 7.
  - **Deps**: T030
  - **Tests**: `usePublishTask.test.tsx` covers `composing → creating → task`, `creating → composing` on a 4xx while keeping the input, and re-partitioning after members change.
  - **Done**: green.
- [X] T032 [US1] Create `frontend/src/pages/publish/PublishMediaPage.tsx` and `PublishTask.tsx` (layout), replacing the temporary mount of `Distribute` on `library/:mediaId/publish` in `frontend/src/routes.tsx`. Loading:
  - the content, plus not found for a foreign or non-existent Media;
  - `getAccountHealth`, `listPlatforms` and `listDistributionPresets`, once;
  - `getContentUsage`;
  - the resolution of the set: without `posts` and with drafts → `replace` to `?posts=<draft ids>`; with `posts` → `getPublication` for each one + `validateMembers`; dropped ids → `replace` + the notice "N posts couldn't be included"; empty → Compose.
  - Also a compact `MediaSummary` (preview, title, type, duration, `Back to media`), `Skeleton`/`ErrorState` + Retry, the page `<h1>` and task mode.
  - **Deps**: T031, T026
  - **Tests**: `frontend/src/pages/publish/publish-page.test.tsx` covers:
    - a Media with 2 drafts and no `posts` → Review + URL rewritten;
    - `?posts` with a foreign id → dropped + notice;
    - not found;
    - bottom nav hidden on `sm`.
  - **Done**: green.
- [X] T033 [US1] Create `frontend/src/pages/publish/destinations.ts` and `compose/DestinationList.tsx`:
  - Eligibility per account from health, platform availability, capabilities, media type and active Posts of the Media (usage `display_state` ≠ draft, published or cancelled).
  - Reasons: "Video only", "Reconnect account", "Finish account setup", "Choose a channel", "Configure in Settings", "Coming soon", "Already scheduled · View post", "Publishing now · View post", "Has a failed post · View post", each with a link where it applies.
  - An account with an active **Draft** of this Media whose id is not in the current `?posts` is not offered for a second draft: it shows "Has a draft" and the action `Add to this task` (implemented in T042).
  - Inactive accounts are hidden; available accounts first. Each destination is a full selectable row (checkbox + label, 44 px).
  - **Deps**: T032
  - **Tests**: `destinations.test.ts` (parametrized per reason) and one render check that disabled rows show their reason and link.
  - **Done**: green.
- [X] T034 [US1] Create `compose/PresetPicker.tsx` and `compose/PresetsDialog.tsx` by extracting the logic of `PresetManager` from `Distribute.tsx`:
  - the picker is a compact selector; applying a preset **replaces** the selection and shows the skipped destinations with their reason, without modifying the preset;
  - `Save as preset` and `Manage presets` (create, rename, change accounts, delete) open a secondary `Dialog`.
  - **Deps**: T033
  - **Tests**: migrate the preset cases of `Distribute.test.tsx` to `presets.test.tsx`: replacement, skipped with reason, duplicate name, delete.
  - **Done**: green.
- [X] T035 [US1] Create `compose/CommonContent.tsx` and `compose/DestinationCustomize.tsx`, plus `frontend/src/pages/publish/snapshot.ts`:
  - Common caption and hashtags prefilled from the Media, with the text "Used for all selected destinations unless customized."
  - `Customize` per destination as progressive disclosure, showing one form at a time; title only for YouTube; no common title; dirty fields; `Discard customization`.
  - No automatic truncation and no adaptation of text to platform limits in the frontend; limits and validation keep coming from the existing backend contracts (FR-025).
  - `buildCreateBody(selected, common, custom, media)` produces only `targets[accountId]` with an explicit `description_override` and `hashtags_override` and, for YouTube, `title_override` (`custom ?? media.title ?? ""`). Empty values are explicit (`""` and `[]`). No common fields, no date, no `auto_publish_enabled`.
  - **Deps**: T033
  - **Tests**: `snapshot.test.ts` (parametrized) covers explicit values with no edits, customization over common, title only for YouTube, explicit empty values, and that no date is sent. `compose.test.tsx` covers that only one form is open at a time.
  - **Done**: green.
- [X] T036 [US1] Implement `Continue` in `PublishTask`:
  - Validation: at least 1 destination; otherwise an `ErrorSummary` (`frontend/src/pages/publish/review/ErrorSummary.tsx`, `role=alert`, focus, links) — this is the component later reused in T045.
  - `createPublications(mid, buildCreateBody(...))`, all or nothing. On 4xx keep the state and map the errors to the destination or field.
  - On success, `replace` to `?posts=<ids in selection order>` → task phase (the Review layout and its focus arrive in T038).
  - **Deps**: T034, T035
  - **Tests**: `compose.test.tsx` covers:
    - no Post is created or patched while composing, including a preset applied and customizations (FakeApi call log);
    - Continue sends the snapshot;
    - a 409 on one account → nothing created and that destination is flagged;
    - the reducer moves to the task phase and the URL contains the created ids (set identity).
  - **Done**: green.
- [X] T037 [US1] Delete `frontend/src/components/Distribute.tsx` and `Distribute.test.tsx`. First confirm that their scenarios exist in T033–T036: creation, atomic error, customize, presets, and PUBLISHED does not block the account. Remove the Distribute CSS from `index.css`.
  - Also check that `YouTubePublishOptions`, `InstagramPublishOptions`, `ThreadsPublishOptions` and `TikTokPublishOptions` are then consumed **only** by `PublicationDetail`/`PublicationControls` (deleted in T063).
  - **Deps**: T036 (the route has used the new page since T032; Review arrives in T038 within the same block series).
  - **Tests**: `npx vitest run src/pages/publish`.
  - **Done**: no import of `Distribute`; the new Media Publish flow has no legacy dependency.

---

## Phase 6: US1/US2 — Review, Resume and destination editing

**Goal**: Review with Content by destination, provenance, platform cards with autosave, a
mixed set, and add/remove destination. Until Phase 7 the drafts can still be published from
legacy Posts.

**Independent Test**: spec US2 scenarios 3–8; mixed set rendered.

- [X] T038 [US1] Create the Review layout in `frontend/src/pages/publish/review/`:
  - collapsed summaries of Destinations and Content;
  - the message "Your drafts are saved. You can finish them later.";
  - `PlatformDetailsList` (one `PlatformDetails` card per Draft inside an `AutosaveRegistry`);
  - a `ResultsSection` scaffold.
  - When there are results, Results go first and Review becomes "Still to finish · N".
  - No "Created N publications".
  - **Deps**: T017–T022, T031, T032
  - After a successful Continue, focus moves to the Review heading.
  - **Tests**: `review.test.tsx` covers a mixed set (`?posts=` with published, failed, needs_action and one draft) → Results with 3 rows and "Still to finish · 1" with a single card; a set without drafts → Results only; focus on the Review heading after Continue.
  - **Done**: green.
- [X] T039 [US2] Create `review/ContentByDestination.tsx` and `review/EditContentDialog.tsx`:
  - The title is "Content by destination". Destinations with exactly the same value and the same provenance are grouped visually, without the word "common".
  - Provenance per field: "Custom text" when there is an override, "Uses the media's caption" when it is `null`.
  - `Customize` edits one destination. `Edit for these destinations` uses a checklist of chosen destinations and shows "Will change: …".
  - `Use the media's caption` sends `PATCH` override `null`.
  - Saving is explicit in the Dialog (`Field`) and goes through `AutosaveRegistry` so it is flushed together with the rest.
  - **Deps**: T038
  - **Tests**: `content-by-destination.test.tsx` covers:
    - a legacy draft inheriting → "Uses the media's caption";
    - a 019 snapshot → "Custom text";
    - grouping only when both value and provenance are equal;
    - "Edit for these destinations" patches only the chosen ones;
    - "Use the media's caption" sends `null`.
  - **Done**: green.
- [X] T040 [US2] Implement add, remove and re-add destination in Review:
  - Add → create 1 draft with a snapshot (`createPublications` with that single target) → `replace ?posts`.
  - Remove → confirmation `Dialog` → `cancelPublication` → drop the id → `replace ?posts`. If the Post is no longer a Draft, do not cancel it; show its current state with a link.
  - On remove, keep the `publication_id` in local React state as "removed from this task" (keyed by account; never persisted, no batch).
  - Re-add the same account **without a reload** → `reactivatePublication` of exactly that id (existing rules, unchanged; it was a Draft without a date, so it comes back as a Draft). On 409, show the message and create nothing.
  - After a reload, or when no id is known as removed from this task → **never** look up historical Cancelled Posts; create a new Draft with the current snapshot (the existing duplicate rules decide).
  - **Deps**: T038, T033
  - **Tests**: `review-destinations.test.tsx` covers:
    - add → URL with the new id;
    - remove with confirmation → Cancelled, id dropped;
    - re-add without reload → reactivates exactly the removed id;
    - re-add after a reload (a historical Cancelled Post of the same Media + account exists) → creates a new Draft and never calls reactivate;
    - a re-add 409 → message with no duplicate.
  - **Done**: green.
- [X] T041 [US1] Implement the set poller in `usePublishTask`: `getPublication` every 2 s **only** for members in `publishing`, stopping when none is left; re-partition on each tick. On reload or back/forward, rebuild from `?posts=` alone (never from the Media's history).
  - **Deps**: T038
  - **Tests**: `publish-page.test.tsx` covers a reload with `?posts=` (1 publishing + 1 published): it polls only the publishing one and shows a Published row when it finishes; after back/forward the same members.
  - **Done**: green.
- [X] T042 [US1] Implement `Add to this task` (spec FR-035, edge cases; contracts/ui.md §2) in `compose/DestinationList.tsx` and in Review's add-destination list:
  - for an account with an active Draft of this Media outside the current `?posts`, the action adds its `publication_id` to the set (`replace ?posts`) and loads it as a member;
  - it never creates or modifies the Post;
  - Scheduled, Publishing, Failed and other non-Draft active Posts keep blocking with `View post`.
  - **Deps**: T040, T033
  - **Tests**: `review-destinations.test.tsx` covers a Draft outside the set → "Has a draft" + `Add to this task` → URL contains its id and no create/patch call; a Scheduled Post → still blocked with `View post`.
  - **Done**: green.

---

## Phase 7: US1/US2 — Final actions, TikTok consent, partial results, Finish later

**Goal**: When + a single CTA + validate-all-before-start + sequential execution with partial
results, plus Finish later.

**Independent Test**: quickstart journeys A, A′, A″, B; spec US1 scenarios 8–14.

- [X] T043 [US1] Create `review/WhenSection.tsx`:
  - `ChoiceGroup` with `Now` (default) and `Schedule`, and a native `input[type=datetime-local]` inside `Field`;
  - the time zone (`Intl…resolvedOptions().timeZone`), a readable preview and the text "AutoPublisher will publish these posts automatically at this time.";
  - when automation is paused (overview), a warning with a link to Settings.
  - **Deps**: T038, T002, T003
  - **Tests**: `final-action.test.tsx` covers the preview and the time zone, and the paused warning with its link.
  - **Done**: green.
- [X] T044 [US1] Create `review/FinalActions.tsx` with `PageActions`: a single primary CTA `Publish to N destinations` / `Schedule N posts` (N = Drafts in review), the tertiary `Finish later`, and no "Save as draft". On `sm` it is a sticky bar that never covers the focused field. The TikTok declaration state is lifted per Post into `usePublishTask`, and `TikTokDetails` receives it.
  - **Deps**: T043, T004, T021
  - **Tests**: `final-action.test.tsx` covers the label and N in a mixed set, and that the CTA is never disabled.
  - **Done**: green.
- [X] T045 [US1] Implement the pre-validation (contracts/api.md §5), with **no writes** before it passes:
  1. `flushAll()`; any card in error → summary.
  2. `getPublishCheck` per Draft, mapped with `platform-state` (`tiktok_consent_required` only counts if the declaration is not accepted).
  3. Schedule: the date is in the future.
  - Failure → reuse the `ErrorSummary` component (focus + links that move focus to the field or card), and keep the inline errors.
  - **Deps**: T044
  - **Tests**: `final-action.test.tsx` covers:
    - one Draft with problems → 0 calls to `tiktok-consent`, `publish` or `PATCH`;
    - the summary is focused and its link moves focus;
    - a pending declaration appears as "TikTok declaration";
    - a past date.
  - **Done**: green.
- [X] T046 [US1] Implement the **Publish now** orchestration in `usePublishTask`:
  - sequential in set order, per Post: (TikTok Direct Post) `confirmTikTokConsent(fp, version)` → `publishNow(id, false)`;
  - an error stops only that Post: "Didn't start · <message>", and the Post stays in its real state;
  - `tiktok_consent_stale` → reset the declaration plus "Confirm the TikTok declaration again";
  - re-partition after each step;
  - once the prevalidation passed and the CTA was pressed, navigating inside the SPA does **not** cancel the sequence: no AbortController or unmount cleanup is attached to the start mutations; the sequence keeps issuing the starts and only stops updating the state of the unmounted component (Posts is where progress is followed). Closing the tab may interrupt requests not yet sent; that is outside this guarantee.
  - **Deps**: T045, T041
  - **Tests**: `final-action.test.tsx` covers:
    - 3 drafts where the 2nd `publish` rejects → the 1st and 3rd start;
    - the order of the consent call before publish;
    - stale → Didn't start while the others continue;
    - unmounting the page after the 1st start → the 2nd and 3rd `publish` calls are still issued;
    - no second confirmation of any kind.
  - **Done**: green.
- [X] T047 [US1] Implement the **Schedule** orchestration:
  - sequential, per Post: (TikTok Direct Post) `confirmTikTokConsent` → `updatePublication(id, {scheduled_at, auto_publish_enabled: true})`;
  - a failure leaves that Post as a Draft with its message; no rollback; no navigation;
  - Results show "3 scheduled · 1 still a draft" and "Still to finish" keeps the CTA `Schedule 1 post` to retry.
  - **Deps**: T046
  - **Tests**: `final-action.test.tsx` covers:
    - 4 drafts where the 4th `PATCH` rejects → exact aggregate, 3 Scheduled kept, no navigation, the retry CTA;
    - paused automation → `scheduled_paused`;
    - every PATCH carries `auto_publish_enabled: true`.
  - **Done**: green.
- [X] T048 [US1] Complete `review/ResultsSection.tsx`:
  - human states per row: Publishing…, Processing (attempt stage), Published, Failed, Needs review, Ready in TikTok, Didn't start;
  - an aggregate line by result (never "Publish failed" on a partial failure) and a polite live region;
  - actions `View posts`, `Back to Library` and `Open post` on rows with problems;
  - while anything is publishing, the text "Publishing continues in the background. Track it in Posts.";
  - focus on the Results heading after the CTA.
  - **Deps**: T046, T047
  - **Tests**: `final-action.test.tsx` covers "2 published · 1 failed" from FakeApi states and `Open post` only on the problem rows.
  - **Done**: green.
- [X] T049 [US2] Implement `Finish later`:
  - `flushAll()` → if there are errors, a `Dialog` "Couldn't save N changes" with `Retry` and `Discard and leave` → `navigate(/p/:pid/posts)` with focus on Drafts (router state);
  - no mutation of its own;
  - `beforeunload` only while Compose is dirty.
  - **Deps**: T045
  - **Tests**: `finish-later.test.tsx` covers:
    - a pending save is flushed before navigating;
    - a failed save → Dialog → Retry or Discard;
    - a FakeApi log with no extra request.
  - **Done**: green.

**Checkpoint**: journey A complete with the new Publish; drafts appear in legacy Posts until Phase 8.

---

## Phase 8: US3 — Posts (List / History)

**Goal**: daily list by product meaning, History separated, readiness from the overview.
`PublicationQueue` disappears.

**Independent Test**: spec US3 scenarios 1–9.

- [X] T050 [US3] Create `frontend/src/pages/posts/usePostsData.ts`:
  - `listPublications` with the current polling (2 s while any Post is `publishing`, 15 s while armed Posts wait, the `utils.ts` constants);
  - `byId`, `reload`, and `onStatusChange → reloadOverview()`;
  - a single poller per page.
  - **Deps**: —
  - **Tests**: `posts-data.test.ts` covers that the interval depends on the data and that a status change calls `reloadOverview`.
  - **Done**: green.
- [X] T051 [P] [US3] Create `frontend/src/pages/posts/readiness.ts` (research R-06):
  - `incomplete` attention items from the overview → `needs_details` with their `detail`, including "Couldn't verify requirements";
  - a Scheduled Post within ≤7 days whose account is not `ready` in account health → `blocked` with its reason;
  - the rest within the horizon → `ready`; beyond 7 days → none;
  - no `local_check` and no endpoint.
  - **Deps**: —
  - **Tests**: `readiness.test.ts` (parametrized).
  - **Done**: green.
- [X] T052 [US3] Create `frontend/src/pages/posts/sections.ts` (contracts/ui.md §4):
  - exclusive precedence: History → Needs you → Upcoming (Publishing now first, then by day: Today, Tomorrow or the date) → Drafts;
  - Needs you order: rank (`needs_review` 1, `failed` 2, `missed` 3, `needs_action` 4, problems 6), then the date;
  - History by month, with a limit of 30 plus `Show more`;
  - search and account filtering.
  - **Deps**: T051
  - **Tests**: `sections.test.ts`, parametrized over every `display_state`: exactly one section; Missed manual and automatic in Needs you; incomplete or blocked scheduled in Needs you; the order; the search filter.
  - **Done**: green.
- [X] T053 [US3] Rewrite `frontend/src/pages/PostsPage.tsx` as the container, with `posts/{DailyList,HistoryList,PostRow,NewPostMenu}.tsx` and `posts.css`:
  - The header shows `Posts` and `New post` (`Publish media…` → Library; `Text post` → `/posts/new`). The `List | Calendar` switch is added in T065.
  - Register `posts/new` (declared before `posts/:postId?`) in `frontend/src/routes.tsx` and **temporarily** mount the legacy `TextPublicationCreate` there directly (on create → `/posts`; on cancel → `/posts`), until T066 replaces it. `Text post` is never hidden and `PublicationQueue` is not kept for this.
  - A toolbar with search and an account select, kept in the URL (`?q`, `?account`).
  - A single project banner when paused (reuse `AutomationPausedBanner`).
  - Sections with headings, each hidden when empty, as `<ul>`. Each row is one `<Link>`: thumbnail or text icon, title or excerpt, platform/account, date, `StatusBadge`, and a next-action hint in Needs you.
  - History lives at `?view=history`.
  - Selection opens `/posts/:id?<same query>` in `DetailSurface panelFrom="lg"`, keyed by id. **Temporarily** the detail mounts the existing `PublicationDetail` (until T063); there is no second list.
  - **Deps**: T050–T052, T005
  - **Tests**: `frontend/src/pages/posts/posts.test.tsx` covers:
    - sections and headings;
    - an empty Needs you is hidden;
    - one paused banner;
    - History grouped by month with Show more;
    - opening a detail keeps the list mounted, with search and scroll;
    - New post offers both options and `/posts/new` resolves (legacy form).
  - **Done**: green.
- [X] T054 [US3] Delete `frontend/src/components/PublicationQueue.tsx` and `PublicationQueue.test.tsx`, migrating their useful cases (order, polling, rows) to T050–T053. Remove the queue CSS from `index.css`. Adapt the Posts steps of `routes.test.tsx` and `onboarding.test.tsx`.
  - **Deps**: T053
  - **Tests**: `npx vitest run src/pages/posts src/routes.test.tsx src/onboarding.test.tsx`.
  - **Done**: no import of `PublicationQueue`; `/posts/new` still works through the temporary legacy form.

---

## Phase 9: US4 — Post detail and recovery

**Goal**: plan §15. Status/action panel, schedule, content, platform details, activity and
cancel. R6 is reachable from the UI and C1 is preserved. The remaining legacy components
disappear.

**Independent Test**: spec US4 scenarios 1–9 and 4a; quickstart journey C.

- [X] T055 [P] [US4] Create `frontend/src/pages/posts/post-actions.ts` following the exact table in contracts/ui.md §5 (FR-071), including Scheduled paused → `Edit schedule` + `Open Settings`, problems + paused → `Complete details` + `Edit schedule`, Failed → `Retry now` / `Reschedule` / `Move to drafts`, and Needs review → only `Check result`. Also the hints for the rows in Needs you.
  - **Deps**: T051
  - **Tests**: `post-actions.test.ts`, parametrized per row of the table.
  - **Done**: green.
- [X] T056 [US4] Create `frontend/src/pages/posts/PostDetail.tsx` and `StatusActionPanel.tsx`:
  - read the Post from `usePostsData.byId` (fallback: one `getPublication` on a deep link), without its own poller;
  - order: header → panel (one sentence, one primary action, at most one secondary) → When (`PostWhen.tsx`) → Content → Platform details → Activity → destructive area;
  - `DetailSurface actions` with the primary action on `sm`;
  - replace the temporary mount of `PublicationDetail` in `PostsPage`.
  - **Deps**: T053, T055
  - **Tests**: `post-detail.test.tsx` covers the section order, the panel per representative state, and no remount when the status changes (state of an open Disclosure is kept).
  - **Done**: green.
- [X] T057 [US4] Create `frontend/src/pages/posts/ActionDialog.tsx` (Dialog on md+, Sheet on sm) for Publish now, Retry now, Reschedule, Edit schedule, Publish automatically and Move to drafts:
  - a summary; a date/time with the time zone and the automatic text when needed; the paused warning with a link;
  - a single `TikTokDeclaration` for TikTok Direct Post in actions that publish or arm, with `confirmTikTokConsent` immediately before the action;
  - calls: `publishNow(id, false)`; `updatePublication(id, {scheduled_at, auto_publish_enabled: true})` for Reschedule and Edit schedule; `{auto_publish_enabled: true}` for Publish automatically; `{scheduled_at: null}` for Move to drafts;
  - on `409 check_result_first`: show "Check the result first."; if the Post whose attempt needs review can be identified reliably from the data already loaded (`usePostsData`: a `needs_review` Post of the same Media + account), offer a `Check result` link to it; otherwise show only the message and point to Needs you. Never retry, never bypass the guard, no new backend.
  - **Deps**: T056, T021, T014
  - **Tests**: `action-dialog.test.tsx` covers:
    - Failed → Reschedule sends a PATCH with arming;
    - Failed → Move to drafts sends `scheduled_at: null`;
    - TikTok: a single declaration and the consent call before the PATCH;
    - Edit schedule on a paused Post;
    - Publish automatically on a legacy manual Post;
    - an unexpected `check_result_first` on a visible Failed → message, plus a `Check result` link only when the related Post is identifiable.
  - **Done**: green.
- [X] T058 [US4] Create `frontend/src/pages/posts/CheckResultDialog.tsx` (spec FR-073a, C1):
  - `getPublishCheck` (read-only reconcile) → reload the Post; if it is resolved, close on the determined state (Published, or Failed with the R6 actions);
  - if it is still uncertain, explain what to check and show the acknowledgement "I checked <platform> and this post was not published"; only then enable `Publish again` → `publishNow(id, true)`, with the single TikTok declaration when it applies;
  - never offer Reschedule or Move to drafts while the result is uncertain.
  - **Deps**: T057
  - **Tests**: `check-result.test.tsx` covers:
    - reconcile resolves → determined state;
    - still uncertain → `Publish again` disabled until acknowledged, then `publish` with `confirm_remote_checked: true`;
    - no Reschedule offered.
  - **Done**: green.
- [X] T059 [US4] Create `frontend/src/pages/posts/PostContent.tsx` and `sent-content.ts` (plan §17):
  - Draft or Scheduled: provenance per field, `Edit` (Field, Save/Cancel) and `Use the media's caption`; for an armed TikTok Post, warn about the consent before saving, using `consent.state` of the TikTok options already loaded by `TikTokDetails` (no new request).
  - Published: the content actually sent, mapped by platform and mode (YouTube title + description, Instagram caption, Threads text, TikTok Direct Post caption, Inbox "You wrote the caption in TikTok", Telegram and legacy → effective content + "May differ from what was sent"), with the current content in a secondary "Current text" disclosure.
  - **Deps**: T056
  - **Tests**: `sent-content.test.ts` (parametrized per platform and mode) and one render case: Published shows what was sent even though the Media changed.
  - **Done**: green.
- [X] T060 [US4] Integrate `PlatformDetails` (Phase 3) into Post detail: collapsed when Ready or Published, open when something is missing, with autosave. `Complete details` scrolls to and focuses the card. For `needs_action`, reuse `TikTokInboxDelivery.tsx` with `Check status`.
  - **Deps**: T056
  - **Tests**: `post-detail.test.tsx` covers incomplete → open and focused by Complete details, Published → collapsed, and Check status on Needs action.
  - **Done**: green.
- [X] T061 [US4] Create `frontend/src/pages/posts/Activity.tsx`, adapting `PublicationAttempts.tsx`:
  - a collapsed `Disclosure` that loads attempts when opened and after a status change;
  - human events ("Tue 18:00 · Started automatically", "Tue 18:01 · Failed: <message>");
  - a second `Disclosure` "Technical details" with codes, attempt ids, stages, external ids and checksums.
  - **Deps**: T056
  - **Tests**: migrate the relevant cases of `PublicationAttempts.test.tsx` to `activity.test.tsx`: humanised text and technical details only after the second disclosure.
  - **Done**: green.
- [X] T062 [US4] Add the destructive area: `Cancel post` (secondary danger action) → `Dialog` "You can reactivate it later" → `cancelPublication`; and `Reactivate` for Cancelled → `reactivatePublication` with its existing semantics (the UI shows the resulting state, whatever it is).
  - **Deps**: T056
  - **Tests**: `post-detail.test.tsx` covers that cancel asks for confirmation and that reactivate calls the existing endpoint and shows the resulting state.
  - **Done**: green.
- [X] T063 [US4] Delete `PublicationDetail.tsx`, `PublicationControls.tsx`, `PublishNowDialog.tsx` (an inline fake dialog), `AutoPublishConsent.tsx`, `AutoPublishBadge.tsx`, `useLivePublication.ts`, `PublicationAttempts.tsx`, `YouTubePublishOptions.tsx`, `InstagramPublishOptions.tsx`, `ThreadsPublishOptions.tsx` and `TikTokPublishOptions.tsx`, plus their tests, once their scenarios are migrated in Phases 3 and 9. Keep `YesNo` if `YouTubeDetails` uses it, by moving it to `components/platform/`. Remove their CSS from `index.css`. Confirm that no `section role="dialog"` remains (`grep`).
  - **Deps**: T056–T062
  - **Tests**: `npx vitest run src/pages/posts src/components/platform`.
  - **Done**: no import of the deleted files; the legacy double TikTok confirmation no longer exists anywhere.

**Checkpoint**: journeys B, C, E complete; no legacy publication surface remains.

---

## Phase 10: US6 — Calendar

**Goal**: read-only Calendar inside Posts.

**Independent Test**: quickstart journey D; spec US6 scenarios 1–5.

- [X] T064 [P] [US6] Create `frontend/src/pages/posts/calendar.ts` (research R-09):
  - `parseWeek(param, today)`: the local Monday; an invalid value → the current week;
  - `weekDays`, `formatRange` (Intl) and `timeZoneLabel`;
  - `calendarMoment(post)`:
    - Published → `published_at`;
    - `scheduled_*` and Missed → `scheduled_at`;
    - Publishing → the execution actually happening: `scheduled_at` if the current attempt is `trigger=scheduled`; if it was started manually (Publish now), `latest_attempt.started_at`; fallback `updated_at` if the main timestamp is missing;
    - Failed and Needs review → `scheduled_at` if `trigger=scheduled`, otherwise `latest_attempt.started_at`;
    - Needs action → `latest_attempt.finished_at`, with `updated_at` as fallback;
  - `postsByDay` excludes `draft` and `cancelled` and sorts by time.
  - **Deps**: —
  - **Tests**: `calendar.test.ts` (parametrized) covers:
    - Published with an old `scheduled_at` uses `published_at`;
    - a Post scheduled for Friday and published manually on Tuesday appears on Tuesday while Publishing;
    - manual vs scheduled failed;
    - needs_action;
    - week parsing, an invalid week, and a Sunday belongs to the week starting on the previous Monday;
    - drafts and cancelled are excluded.
  - **Done**: green.
- [X] T065 [US6] Create `posts/{CalendarView,CalendarWeek,CalendarAgenda}.tsx` and add the `List | Calendar` switch (`ChoiceGroup variant="switch"`) to `PostsPage`:
  - URL `?view=calendar&week=YYYY-MM-DD`; an invalid value → `replace`; previous / Today / next use push;
  - the date range and the time zone are visible;
  - week view at ≥1024 px (one `<section>` per day with `<h3>` and a `<ul>`, compact blocks, same-time items stacked); agenda below 1024 px;
  - state shown with icon and text; an empty week shows a neutral message;
  - search and account filters apply; opening a Post uses `DetailSurface panelFrom="xl"`;
  - no `role=grid`, no drag, no slot creation.
  - **Deps**: T064, T053, T056
  - **Tests**: `calendar-view.test.tsx` covers:
    - navigating to the next week updates the URL and survives a reload (memory router);
    - the agenda without `matchMedia`;
    - a Post opens its detail;
    - no Drafts.
  - **Done**: green.

---

## Phase 11: US7 — Text-only Publish (same architecture)

**Goal**: `/posts/new` reuses `PublishTask` and `usePublishTask` with `mode="text"`.

**Independent Test**: quickstart journey F; spec US7 scenarios 1–4.

- [X] T066 [US7] Create `frontend/src/pages/publish/PublishTextPage.tsx` and replace the temporary legacy mount of `posts/new` (T053) with it, adding `handle.taskMode`, in `frontend/src/routes.tsx`:
  - `mode="text"` in `usePublishTask`, `destinations.ts` and `PublishTask`: no MediaSummary;
  - a required text (`Field`) plus hashtags;
  - destinations need `capabilities.includes("text")` from account health, and the rest are disabled with "Needs media";
  - Compose has no per-destination Customize (plan C3);
  - `Continue` → `createTextPublications` → `replace ?posts=`;
  - Review, When, validation, actions, results and Finish later are the shared ones, with no fork;
  - delete `frontend/src/components/TextPublicationCreate.tsx` and its test in this task (its scenarios migrate to `publish-text.test.tsx`).
  - **Deps**: T049, T048, T053
  - **Tests**: `publish-text.test.tsx` covers:
    - required text → summary;
    - "Needs media" disabled;
    - Continue uses the text endpoint and writes `?posts=`;
    - Schedule and Publish now reuse the orchestration (one case each);
    - customization in Review through PATCH.
  - **Done**: green.
- [X] T067 [US7] Text resume:
  - `?posts=` validates `content_id === null`; a Post with Media → dropped + notice;
  - Post detail `Continue setup` → `/posts/new?posts=<id>`, and `New post → Text post` opens `/posts/new`;
  - delete `TEXT_POST_PLATFORMS` (`types.ts`) and `textPostAccounts` (`utils.ts`) once they are unused (plan C6).
  - **Deps**: T066, T056
  - **Tests**: `publish-text.test.tsx` covers reload with `?posts=<text id>` → Review of that draft, Finish later → Drafts, and Continue setup from detail.
  - **Done**: no import of the deleted items.

---

## Phase 12: Responsive and cross-cutting accessibility (short review)

- [X] T068 Responsive review of every new route at 375, 768, 1024–1279 and ≥1280 px, fixing the CSS of the touched files:
  - 375: Library has 2 columns; Media and Post detail are full-screen with the bottom nav; Posts rows are full width; Calendar is an agenda; Publish runs in task mode without the bottom nav, with `PageActions` sticky; there is no horizontal scroll of the document.
  - 768: rail, Library about 4 columns, details in a Drawer, agenda.
  - 1024–1279: Posts has the side panel; Library and Calendar use a Drawer.
  - ≥1280: sidebar, Library 5–6 columns without a detail, a side `DetailSurface`, Calendar week.
  - Following the user's preference, start the backend and frontend in the background and give the link for the manual check.
  - **Deps**: Phases 4–11
  - **Tests**: no new automated tests except `routes.test.tsx` for task mode, already covered.
  - **Done**: a checklist of findings fixed.
- [X] T069 Short cross-cutting accessibility review of the new surfaces:
  - headings, labels and fieldsets; `aria-current` and `aria-busy`;
  - error summaries focused; focus returns from details and dialogs;
  - Dialog/Drawer traps; sticky bars never cover the focus;
  - full keyboard use (Library → Media → Publish → CTA; Posts → detail → action);
  - reduced motion; 44 px targets; status never conveyed by colour alone.
  - Fix only what is found.
  - **Deps**: T068
  - **Tests**: only the targeted tests of the files fixed.
  - **Done**: no open findings.

---

## Phase 13: Feature close

- [X] T070 Remove legacy remnants and orphans:
  - unused CSS in `frontend/src/index.css` (Library, Distribute, queue, publication detail, dialog classes);
  - helpers in `frontend/src/utils.ts` and `types.ts` with no consumer (`PUBLICATION_STATUS_LABELS`, `publicationStatusLabel`, `isPublishable`, `hasPlatformOptions`… only if they are unused) and their tests in `utils.test.ts`;
  - confirm with `grep` that no import of deleted components remains.
  - **Deps**: T067, T069
  - **Tests**: `npx vitest run src/utils.test.ts`.
  - **Done**: no orphans.
  - **Note (close)**: FR-076 checksums in Post detail → Technical details: resolved after the close review by recording `submitted.file_checksum` (the checksum of the file `prepare()` resolved for that attempt) when the attempt is created; additive, no column, migration or endpoint; older attempts without it show no checksum row, and the Media's current checksum is never used as a fallback.
- [X] T071 Review copy and terminology in the new UI: no Publication, Asset, Queue, Distribute, Prepare, Unscheduled, attempt, scheduler state, armed or internal codes outside "Technical details" (`grep` over JSX strings in `frontend/src/pages` and `components/platform`).
  - **Deps**: T070
  - **Tests**: targeted tests of the files changed.
  - **Done**: no forbidden term in the normal UI.
- [X] T072 Update the docs:
  - `docs/design-system.md`: `Field`, `ChoiceGroup`, `PageActions`, the `xl` breakpoint, `DetailSurface panelFrom` and `actions`, `taskMode`, and the adopted UI UX Pro Max recommendations;
  - `README.md`: Library, Publish (Compose → Review, Finish later, Schedule = automatic), Posts (List, History, Calendar), Post detail (Retry, Reschedule, Move to drafts, Check result), text posts;
  - `docs/asset-library.md` if it describes the old detail.
  - In English.
  - **Deps**: T071
  - **Tests**: none.
  - **Done**: the docs reflect the visible behaviour.
- [X] T073 Run the **pending** targeted tests (only blocks whose code changed after their last green run) and the static checks **once**:
  - backend: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`;
  - frontend: `npm run lint`, `npm run format:check`, `npm run typecheck`, `npm run build`;
  - `git diff --check`.
  - Do **not** run the full pytest or Vitest suite (that is CI's job).
  - **Deps**: T072
  - **Tests**: those listed.
  - **Done**: everything green.
- [X] T074 Security and privacy review of the diff:
  - `?posts=` validated;
  - "Technical details" shows no tokens, upload URLs or publish ids;
  - `submitted` is shown without secrets;
  - the Creator Info avatar is not persisted;
  - error messages show only the safe `message`;
  - no paths in the normal UI;
  - no new logs.
  - Use `/security-review` if it applies.
  - **Deps**: T073
  - **Tests**: none beyond fixes, each with its targeted test.
  - **Done**: no findings, or findings fixed.
- [X] T075 Check the feature boundary in the diff:
  - nothing from Feature 020;
  - Republish, editable calendar, bulk management, pagination, sorting, thumbnails, Post deletion and a batch entity are all absent;
  - Reactivate, the scheduler, the publishers and the overview are unchanged;
  - no migrations;
  - R6 is the only lifecycle change.
  - Mark the checkpoints done in `quickstart.md`.
  - **Deps**: T074
  - **Tests**: none.
  - **Done**: the boundary is confirmed.

Not included in the automatic execution: commit, push, PR and merge (Git close of the feature).
If CI fails: reproduce only the failure → fix → targeted test → relevant static checks →
push; CI repeats the full suite.

---

## Dependencies & Execution Order

```text
Phase 1 (T001–T006) ─┬─> Phase 3 (T015–T022) ─┐
Phase 2 (T007–T014) ─┴─> Phase 4 US5 (T023–T029) ─> Phase 5 US1 (T030–T037)
                                                   └─> Phase 6 (T038–T042) ─> Phase 7 (T043–T049)
Phase 7 ─> Phase 8 US3 (T050–T054) ─> Phase 9 US4 (T055–T063) ─> Phase 10 US6 (T064–T065)
Phase 7 + Phase 9 ─> Phase 11 US7 (T066–T067) ─> Phase 12 (T068–T069) ─> Phase 13 (T070–T075)
```

Key dependencies:
- The primitives (Phase 1) come before every surface.
- The backend contracts (T008–T014) come before Library, Usage and Post detail.
- `publish-set.ts` (T030) comes before the mixed set (T038, T041).
- Autosave (T015) comes before Review (T038) and Finish later (T049).
- The TikTok declaration (T021–T022) comes before the actions (T046–T047, T057).
- The Failed lifecycle in the backend (T012–T013) comes before `ActionDialog` (T057).
- The shared Publish architecture (Phases 5–7) comes before text mode (T066).


## Parallel opportunities

Only tasks that touch disjoint files with no pending dependency:
- **Phase 1**: T002, T003 and T004. T004 after T001.
- **Phase 3**: T016 alongside T015; T018, T019 and T020 after T017. T021 does not depend on T017.
- **Phase 4**: T023, as soon as T014 is done.
- **Phase 8**: T051 alongside T050.
- **Phase 9**: T055.
- **Phase 10**: T064, which can start as soon as Phase 8 exists.

## Implementation strategy

1. **MVP**: Phases 1–7. This gives the new Library with Media detail and a complete Media
   Publish flow (journeys A, A′, A″, B up to Finish later). Posts and detail still run on
   legacy, so the app stays usable.
2. Phases 8–9 replace Posts and Post detail and remove all the legacy publication code
   (journeys B, C, E).
3. Phases 10–11 add Calendar and Text post (journeys D, F).
4. Phases 12–13: cross-cutting review and close.

## Coverage map (FR → tasks)

| FR | Tasks |
|---|---|
| FR-001–007 Library | T023–T026, T029 |
| FR-008–015 Media detail | T026–T028 |
| FR-016–018 Publish route/task mode | T006, T026, T032 |
| FR-019–025 Compose | T033–T036 |
| FR-026–029 Continue/snapshot | T035, T036 |
| FR-030–031a Review/Resume/identity | T030, T032, T038, T041 |
| FR-032–035 Content by destination, edit destinations | T039, T040, T042 |
| FR-036–039 Platform details | T016–T020, T038 |
| FR-040–046 Platform requirements | T018–T022 |
| FR-047 TikTok single declaration | T021, T022, T044, T046, T047, T057, T058 |
| FR-048–051 When/CTA/Finish later | T043, T044, T049 |
| FR-052–052a Validation/partial Schedule | T045, T047 |
| FR-053–054 Publish now result | T046, T048 |
| FR-055–061 Posts | T050–T054 |
| FR-062–063 Rows/selection | T053 |
| FR-064–065 Readiness | T051 |
| FR-066–069 Calendar | T064, T065 |
| FR-070–072 Post detail/actions | T055–T057, T060 |
| FR-073–073a Failed R6 / Check result (C1) | T012, T013, T057, T058 |
| FR-074 Published sent content | T059 |
| FR-075–076 Platform details/Activity in detail | T060, T061 |
| FR-077–078 Cancel/Reactivate unchanged | T062, T013(8) |
| FR-079–081 Text posts | T066, T067 |
| FR-082–085 Usage read-model | T008–T011, T014 |
| FR-086–090 Responsive | T001, T004–T006, T024, T065, T068 |
| FR-091 Visual | T024–T065 (tokens), T070 |
| FR-092–094 Accessibility | inside each block, plus T069 |
| FR-095 Design system | T001–T006 |
