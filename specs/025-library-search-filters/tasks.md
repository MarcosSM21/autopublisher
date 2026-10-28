---

description: "Task list for Feature 025 — Library Search, Filters & Organization"
---

# Tasks: Library Search, Filters & Organization

**Input**: Design documents from `specs/025-library-search-filters/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[contracts/ui.md](contracts/ui.md), [quickstart.md](quickstart.md). No `data-model.md` and no
API contract (no model or API change).

**Tests**: required by the spec ("Testing y criterios de aceptación"). In each checkpoint, tests
are written first and must fail (or not exist yet) before the implementation tasks.

**Organization**: by checkpoint (A–E), the required technical order. Story labels map tasks to
the spec's user stories:

| Checkpoint | User Stories | Priority |
|---|---|---|
| A — Search / filter / sort model | US1, US2, US5 (logic) + US4 (URL model) | P1/P2 |
| B — Desktop Library controls | US1, US2, US3, US5 (desktop UI, URL, selection) | P1/P2 |
| C — Navigation context | US4 (Detail, deep links, Publish) | P2 |
| D — Mobile & result UX | US7, US8, US6 | P2/P3 |
| E — Polish, docs & verification | cross-cutting | — |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task).
- **[Story]**: US1–US8 (spec.md).

## Closed decisions (plan.md, "Decisiones confirmadas")

- FR-062: the two-row limit is checked at the Library's normal content width. With the detail
  side panel open, the toolbar may wrap; there is never horizontal overflow; no new breakpoint.
- Desktop: search + four `select` controls inside `Field` (Type, Usage, Imported, Sort). The
  Media type pills are removed.
- Focus fallback: the shell `<main>` (`id="main-content"`, already `tabIndex={-1}` in `AppShell`; the decision called it `id="main"`), never `<body>`.

## UI copy (closed, contracts/ui.md)

- Selects: `Type` (All · Images · Videos), `Usage` (All · Used · Unused), `Imported` (Any time ·
  Last 7 days · Last 30 days · Last 90 days), `Sort` (Newest · Oldest · Name A–Z · Name Z–A).
- Chips: value label (`Videos`, `Unused`, `Last 30 days`); accessible name `Remove filter:
  <label>`; group `Active filters`; `Clear all`.
- Mobile: `Filters` / `Filters · N` (accessible name `Filters` / `Filters, N active`); Sheet
  `Filters` with `Clear filters` and `Done`.
- Empty results: `No media match "<q>"`, `No media match these filters`, `No media match the
  search and filters`; actions `Clear search`, `Clear filters`, `Search all media`.
- Status region: empty, `N media` or `No media`.

## Testing policy (CLAUDE.md)

- Targeted Vitest files only, once per checkpoint; never the full frontend suite locally.
- No backend tests: the backend does not change.
- Lint, format, typecheck and build only once, in E. Full suites only in PR CI.
- Tests use `renderRoute` (`frontend/src/test-utils.tsx`), the fake API
  (`frontend/src/test-fake-api.ts`) and an injected `now` for dates; never `sleep`.
- **Viewport**: jsdom has no `matchMedia`, so `useMediaQuery` answers `false` and every test runs
  the **mobile** layout by default. `setViewport(width)` is NOT in `test-utils.tsx`: it is a
  local helper of each test file (e.g. `library.test.tsx`). `search-filters.test.tsx` copies that
  helper (the minimal option; no shared util). Every test that uses the desktop selects calls
  `setViewport(1300)` explicitly, so desktop tests keep testing desktop once D adds the mobile
  layout.

---

## Phase 1: Setup

**Purpose**: a known-green baseline of the tests the feature touches, so regressions can be
attributed.

- [X] T001 Run once, before any change: `cd frontend && npx vitest run src/pages/library/library.test.tsx src/pages/library/library-helpers.test.ts src/pages/library/move.test.tsx src/pages/library/bulk-delete.test.tsx src/pages/library/folders.test.tsx src/pages/library/media-content.test.tsx src/pages/publish/publish-page.test.tsx src/pages/publish/usePublishTask.test.tsx src/routes.test.tsx src/ui/detail-surface.test.tsx`; record the result (the regression set of B and C)

---

## Phase 2: Checkpoint A — Search / filter / sort model (US1, US2, US5, US4) 🎯 foundation

**Goal**: pure, UI-free logic for normalization, search, Used/Unused, Imported, sorting, the
result pipeline, the filter dimensions and chips, the URL query model, the Publish return
grammar, and the `useLibraryQuery` hook (research R1–R8, R10, R16).

**Independent Test**: `library-helpers.test.ts` and `library-query.test.ts` pass with table-driven
cases and a fixed `now`; no component renders.

### Tests for Checkpoint A (write first)

- [X] T002 [P] [US1] Add search tests to `frontend/src/pages/library/library-helpers.test.ts`:
  - `normalizeText` removes diacritics and lowercases (`Café`→`cafe`, `NIÑO`→`nino`);
  - `tokenize` splits on whitespace, strips every leading `#` per token, and drops empty tokens
    (`"  #  ##summer  "`→`["summer"]`);
  - matching requires every token in any field (title, `original_filename`, description,
    hashtags), in any order and across different fields (`cafe verano` finds title "Café de
    verano"; `cafe invierno` does not);
  - a token never matches across two fields;
  - special characters are literal (`img_2045`, `a.b`, `50%`, `(1)`, emoji);
  - an empty or whitespace-only query matches everything;
  - a Media without title matches by filename.
- [X] T003 [P] [US2] Add filter tests to `frontend/src/pages/library/library-helpers.test.ts`:
  - `usageOf`: no Posts, only cancelled, draft, scheduled, failed, published, and a mix. Assert
    the partition: used + unused = all, never both.
  - `isNotUsedYet` stays equal to `usageOf === "unused"`.
  - `importedWithin` for 7/30/90 with a fixed `now`: exactly N × 24 h → inside (inclusive);
    1 ms older → outside; future date → inside.
  - Type filter.
  - A generated table covering all 36 combinations type × usage × imported over a fixed fixture,
    with expected ids computed independently in the test (SC-004).
- [X] T004 [P] [US5] Add sort tests to `frontend/src/pages/library/library-helpers.test.ts`:
  - newest = `created_at` desc then `id` desc (same order as the backend fixture);
  - oldest = exact inverse;
  - name-asc and name-desc over `title ?? original_filename`: case and accent insensitive,
    `a2` before `a10`;
  - ties (same name, same `created_at`) fall back to newest in both directions;
  - the input array is not mutated.
- [X] T005 [P] [US2] Add pipeline and chip tests to
  `frontend/src/pages/library/library-helpers.test.ts`:
  - `libraryResults(contents, query, now)` combines search AND type AND usage AND imported, then
    sorts;
  - changing only sort never changes the set;
  - `activeFilters` returns chips in Type, Usage, Imported order with their labels;
  - `withoutFilter` resets only its dimension;
  - `clearFilters` resets the three dimensions and keeps `q` and `sort`;
  - `hasActiveFilters`;
  - `emptyResultsKind` returns `search`, `filters` or `both`.
- [X] T006 [P] [US4] Create `frontend/src/pages/library/library-query.test.ts`:
  - `parseLibraryQuery`: defaults; valid values; invalid or unknown values fall back to default
    (`type=gif`, `sort=size`, `imported=365`); repeated params use the first one.
  - `serializeLibraryQuery`: omits defaults and blank `q`; fixed key order `q, type, usage,
    imported, sort`; round-trip `parse(serialize(x)) == x`; returns `""` or `?…`.
  - `selectionKey`: excludes `sort`; changes when `q`, `type`, `usage` or `imported` change.
- [X] T007 [P] [US4] Add Publish return tests to
  `frontend/src/pages/library/library-query.test.ts`:
  - `libraryReturnParam(scope, query)` encodes `all`, `unsorted` and `folders/<id>` plus the
    serialized query;
  - `parseLibraryReturn` accepts only `all | unsorted | folders/<positive id>` with an optional
    query, re-parses that query and drops unknown params;
  - it rejects every other value: `//evil.com`, `https://x`, `/p/2/library/all`, `../`,
    `folders/0`, `folders/abc`, `posts`, an empty string, an encoded `javascript:`, and an
    over-long id.

### Implementation for Checkpoint A

- [X] T008 [US2] Add `usageOf(content): "used" | "unused"` (`publication_count >
  cancelled_count`) to `frontend/src/pages/library/usage-indicator.ts` and redefine
  `isNotUsedYet` through it. Never read `usage.used` (research R4).
- [X] T009 [US1] Rewrite the search part of `frontend/src/pages/library/library-filters.ts`:
  - `normalizeText` (`NFD` + strip `\p{M}` + lowercase);
  - `tokenize`;
  - `searchText(content)`: normalized fields joined with `"\n"`;
  - `searchIndex(contents) → Map<id, string>`;
  - `matchesTokens(text, tokens)`.

  No regex built from user input (research R3).
- [X] T010 [US2] Add the filter model to `frontend/src/pages/library/library-filters.ts`:
  - `importedWithin(content, days, now)` (inclusive, `Date.parse`);
  - `FILTER_DIMENSIONS`: the single table of keys, labels, options and chip labels for Type,
    Usage and Imported;
  - `activeFilters`, `withoutFilter`, `clearFilters`, `hasActiveFilters`, `emptyResultsKind`.

  Remove `LibraryFilter`, `LIBRARY_FILTERS` and the old `filterMedia` once their callers move
  (in T018).
- [X] T011 [US5] Add sorting to `frontend/src/pages/library/library-filters.ts`:
  - a module-level `Intl.Collator(undefined, { sensitivity: "base", numeric: true })`;
  - comparators for newest, oldest, name-asc and name-desc, with the newest tie-break;
  - `sortMedia(list, sort)` returns a new array (research R6).
- [X] T012 [US2] Add `libraryResults(contents, query, now, index?)` to
  `frontend/src/pages/library/library-filters.ts`: one `filter` pass (type → usage → imported →
  search) then `sortMedia`; returns the results and their `visibleIds` (research R7).
- [X] T013 [US4] Create `frontend/src/pages/library/library-query.ts`:
  - `LibraryQuery` type, `DEFAULT_LIBRARY_QUERY`, `parseLibraryQuery(params)`,
    `serializeLibraryQuery(query)`, `selectionKey(query)`;
  - `libraryReturnParam(scope, query)` and `parseLibraryReturn(value)`, with the closed grammar
    and a rebuilt destination, never the raw string (research R2, R10).
- [X] T014 [US4] Create `frontend/src/pages/library/useLibraryQuery.ts`, the only reader and
  writer of the Library query:
  - `useSearchParams` → `query` (memoized on `location.search`) and `search`;
  - `update(patch)`, `clearSearch()`, `clearFilters()`, `removeFilter(key)`, all writing with
    `{ replace: true }` and preserving `location.state`;
  - no `useState` and no effect that writes the URL on load (research R1).
- [X] T015 Run `cd frontend && npx vitest run src/pages/library/library-helpers.test.ts src/pages/library/library-query.test.ts`; all green. Pre-existing `filterMedia` tests in `library-helpers.test.ts` are replaced by T002–T005, not kept in parallel.

**⛔ STOP A — model and URL review**:
- the search, Used/Unused, Imported and sort semantics match `contracts/ui.md` §2;
- the URL contract matches §1;
- `parseLibraryReturn` cannot produce a destination outside `/p/:projectId/library/…`.

Commit A (`feat: add library search, filter and sort model`) after approval.

---

## Phase 3: Checkpoint B — Desktop Library controls (US1, US2, US3, US5)

**Goal**: at ≥768 px the Library has search + Type/Usage/Imported/Sort selects, combinable
filters, active filter chips with `Clear all`, `Clear search`, the URL as the only source of
truth, the derived safe selection and the results announcement. Opening and closing a Media
detail keeps the query (N1, N2, N3, N11), so STOP B never loses the search or filters, unlike
today's local state. At the end of B, the feature works on desktop (the other navigations,
Publish, mobile and empty-state polish come later).

**Independent Test**: `search-filters.test.tsx` (desktop cases) and the updated
`library.test.tsx` pass at 1300 px with the fake API.

### Tests for Checkpoint B (write first)

- [X] T016 [P] [US2] Create `frontend/src/pages/library/search-filters.test.tsx` with fixtures, a
  local `setViewport` helper (copied from `library.test.tsx`) and desktop control/URL cases, each
  calling `setViewport(1300)` explicitly:
  - typing `cafe verano` filters and writes `?q=cafe+verano` with `replace` (history length
    unchanged);
  - choosing Type=Videos, Usage=Unused and Imported=Last 30 days writes
    `type=videos&usage=unused&imported=30d` and shows only matching cards;
  - Sort=Name A–Z reorders without changing the set and writes `sort=name-asc`;
  - `renderRoute` with all params restores inputs, selects and results (deep link / reload);
  - invalid params show defaults without error;
  - router back/forward between two Library URLs restores the state;
  - N1: a card link keeps the path and every param;
  - N2: an imported Media's link in the import panel keeps the params;
  - N3: closing the detail returns to the same view with the same params and focuses the card,
    in panel (`setViewport(1300)`), drawer (`setViewport(900)`) and page (`setViewport(375)`);
  - N11: the legacy `library/:mediaId?q=…` closes to `/all?q=…`.
- [X] T017 [P] [US2] Add chip cases (`setViewport(1300)`) to
  `frontend/src/pages/library/search-filters.test.tsx`:
  - one chip per non-default dimension, in order, with accessible names `Remove filter: …`;
  - sort and folder never appear as chips;
  - removing a chip resets only that dimension, and focus moves to the next chip, or to that
    dimension's select when it was the last one;
  - `Clear all` resets the filters, keeps `q` and `sort`, and moves focus to the Type select;
  - `Clear search` empties `q` and keeps the filters.
- [X] T018 [P] [US3] Add selection-safety cases (`setViewport(1300)`) to
  `frontend/src/pages/library/search-filters.test.tsx`, starting each from Select with 3 checked:
  - each of the following leaves "0 selected", disables Move/Delete and keeps Select active:
    the first typed character, the Type, Usage and Imported selects, removing a chip,
    `Clear all`, `Clear search`, and router back after a filter change;
  - changing only Sort keeps all 3 checked;
  - after re-checking 2 visible items, Move sends exactly those 2 ids and Delete's preview
    request contains exactly those 2 ids (assert the fake API's recorded payloads);
  - a checked Media that stops matching after a reload (edited via the API) is not sent by Move;
  - frozen Move: check 2 Media, press Move (picker open, titled `Move 2 media`), then router back
    and forward so the query state changes, then confirm a destination. Exactly the 2 frozen
    ids are moved (fake API payload) and the picker title never changed;
  - switching to another folder resets the selection (unchanged behaviour).
- [X] T019 [P] [US1] Add a results-announcement case (`setViewport(1300)`) to
  `frontend/src/pages/library/search-filters.test.tsx`: the `role="status"` region is empty
  without search or filters; it reads `N media` or `No media` with them; its text does not
  change when only Sort changes.
- [X] T020 [P] [US2] Update `frontend/src/pages/library/library.test.tsx`:
  - replace the "Not used yet" radio interactions with the Usage select (`Unused`) and the
    removed pills with the Type select;
  - every case that uses those selects calls `setViewport(1300)` explicitly, including
    "searches by hashtag and filters Not used yet, locally", which runs at the default (mobile)
    width today;
  - keep every other assertion (SC-010);
  - keep "returns to the same search and focus" working through the URL.

### Implementation for Checkpoint B

- [X] T021 [US2] Create `frontend/src/pages/library/LibraryFilters.tsx` (desktop branch):
  - search `input type="search"` (accessible name "Search media", existing placeholder) with a
    `Clear search` action while non-empty;
  - four `select` controls in `Field` (`Type`, `Usage`, `Imported`, `Sort`) driven by
    `FILTER_DIMENSIONS` and the sort options;
  - every change goes through `useLibraryQuery`.
- [X] T022 [US2] Add the active-filter chips to `frontend/src/pages/library/LibraryFilters.tsx`
  (or a local `ActiveFilters.tsx` in the same folder): `Button` + `Icon` close; group `Active
  filters`; `Clear all`; the focus rules of contracts/ui.md §4. No generic chip component in
  `ui/`.
- [X] T023 [US1] Add the visually hidden `role="status"` results region to
  `frontend/src/pages/library/LibraryFilters.tsx`: empty without search or filters, otherwise
  `N media` or `No media`. No visible counter.
- [X] T024 [US2] Reduce `frontend/src/pages/library/LibraryToolbar.tsx` to the header:
  - title, count, Import, Select, actions;
  - filters rendered as `children` below it;
  - remove the `ChoiceGroup` pills and the `query`/`filter`/`showSearch` props.

  Update `frontend/src/pages/library/LibraryRoot.tsx` to the new props (the root still has no
  search).
- [X] T025 [US2] Wire `frontend/src/pages/library/MediaView.tsx` to the URL:
  - replace `useState(query/filter)` with `useLibraryQuery`;
  - `searchIndex` memoized on `contents`;
  - `results` and `visibleIds` memoized on `contents` + `search`, with `now = Date.now()`
    inside the memo;
  - `MediaGrid` receives `results`;
  - `<LibraryFilters>` renders only when the view has Media (FR-060);
  - add `withSearch(path)` (appends the serialized Library query) and apply it now to
    `mediaPath` (N1 card links, N2 ImportPanel links) and `parentPath` (N3 detail close in
    panel, drawer and page; N11 legacy `library/:mediaId` closing to `/all`). The other
    navigations wait for T034.
- [X] T026 [US3] Implement the derived selection in `frontend/src/pages/library/MediaView.tsx`:
  - `checked: { key, ids } | null`;
  - `effective = key !== selectionKey(query) ? ∅ : ids ∩ visibleIds`;
  - `toggle` (computing from `effective` inside the updater), the `SelectionBar` count and
    `setBulkDelete` use `effective` only;
  - pressing Move freezes `movingIds = [...effective]` (same strategy as the existing
    `bulkDelete` snapshot); the `FolderPicker` title (`Move N media`) and `moveChecked` →
    `moveContents` use `movingIds`, never a selection recomputed when the move is confirmed;
  - keep the existing `load()` pruning;
  - no new `useEffect` (research R8).
- [X] T027 [US2] Style the desktop filters row and the chips row in
  `frontend/src/pages/library/library.css`: `flex-wrap`, search `flex: 1 1 14rem`, compact
  selects, no horizontal overflow. Remove the obsolete `.ap-library__filters .ap-choice` rules.
- [X] T028 Run `cd frontend && npx vitest run src/pages/library/search-filters.test.tsx src/pages/library/library.test.tsx src/pages/library/move.test.tsx src/pages/library/bulk-delete.test.tsx src/pages/library/folders.test.tsx`; all green.

**⛔ STOP B — desktop and selection-safety review** (scratch instance per `quickstart.md`, servers
left running): scenarios 1–4 and 7 at 1024 and 1280 px. Check that the toolbar fits two rows at
normal width, that a selection never survives a search or filter change, and that Move and
Delete act only on visible items. Commit B (`feat: add desktop library filters and safe
selection`) after approval.

---

## Phase 4: Checkpoint C — Navigation context (US4)

**Goal**: every Library navigation keeps the query. A deep link to a hidden Media opens its
detail. A Media that stops matching keeps its detail open. Closing the detail focuses the card
or `main` (panel, drawer and page). Library → Publish → "Back to media" restores the view and the
query through a validated `from`. Direct entry to Publish keeps its fallback.

**Independent Test**: the C cases in `search-filters.test.tsx`, `publish-page.test.tsx` and
`usePublishTask.test.tsx` pass, including one test per navigation in the inventory below.

**Navigation inventory** (research R9). N1, N2, N3 and N11 are done in B (T016 tests, T025
`withSearch`); C covers N4–N14 (tests T029–T033, implementation T034–T039):

- N1 card link
- N2 ImportPanel link
- N3 detail close: panel (1300), drawer (900), page (375)
- N4 redirect of another view's Media to `/all/:id`
- N5 `handleMoved` (follow the Media)
- N6 `moveChecked` closing the detail
- N7 `mediaDeleted`: from the detail and from a card menu
- N8 `selectionDeleted`
- N9 `selectionMissing`
- N10 `folderDeleted`: to the parent folder (keeps params) and to the root (drops params)
- N11 legacy `library/:mediaId` closing to `/all` + query
- N12 Publish link carries `from`
- N13 "Back to media" with a valid `from`
- N14 "Back to media" without, or with an invalid, `from`

Breadcrumbs and subfolder entries are new-view navigation and do not carry the query
(unchanged; FR-042 lists only the navigations above).

### Tests for Checkpoint C (write first)

- [X] T029 [P] [US4] Add redirect cases to `frontend/src/pages/library/search-filters.test.tsx`
  (`setViewport(1300)`):
  - N4: a Media of another folder, opened under that folder's view with params, redirects to
    `/all/:id` keeping the params;
  - after the redirect, closing the detail lands on `/all` with the same params.
- [X] T030 [P] [US4] Add deep-link and focus-fallback cases to
  `frontend/src/pages/library/search-filters.test.tsx`: `…/all/<image id>?type=videos` opens the
  detail, no card is marked, and closing focuses the shell `<main>`, never `body`, in panel
  (`setViewport(1300)`), drawer (`setViewport(900)`) and page (`setViewport(375)`) (FR-080,
  FR-082).
- [X] T031 [P] [US4] Add "stops matching" cases to
  `frontend/src/pages/library/search-filters.test.tsx`: with `q=summer`, edit the open Media's
  title so it no longer matches. The detail stays open, the card leaves the grid after the
  reload, and closing focuses `main` (drawer and panel) (FR-081, FR-082).
- [X] T032 [P] [US4] Add move/delete navigation cases to
  `frontend/src/pages/library/search-filters.test.tsx`, each asserting the resulting
  `pathname + search`:
  - N5: moving the open Media to another folder follows it with the params;
  - N6: bulk Move including the open Media closes it to the view with the params;
  - N7: deleting from the detail and from a card menu keeps the params;
  - N7 focus (FR-082): after confirming Delete from the detail and once the confirmation dialog
    and the detail are closed, focus is on the shell `<main>` (or the neighbour card the
    existing `cardLeaving` picks), never on `body` and never on a removed trigger. Check it in
    the drawer (`setViewport(900)`) and the page (`setViewport(375)`);
  - N8 and N9: bulk delete success and the missing case keep the params;
  - N10: deleting a nested folder lands on its parent with the params; deleting a top-level
    folder lands on the Library root.
- [X] T033 [P] [US4] Add Publish return cases to
  `frontend/src/pages/publish/publish-page.test.tsx` and
  `frontend/src/pages/publish/usePublishTask.test.tsx`:
  - N12: the detail's Publish link is `…/publish?from=folders%2F<id>%3Fq%3D…`;
  - N13: with a valid `from`, "Back to media" goes to `/library/folders/<id>/<mediaId>?q=…`;
  - `?posts=` writes (Continue) keep `from`;
  - N14: without `from` (entry from Posts, direct URL) and with invalid values (`//evil.com`,
    `https://x`, `folders/abc`, another project's path), "Back to media" goes to
    `/p/:id/library/:mediaId`, as today.

### Implementation for Checkpoint C

- [X] T034 [US4] Apply the `withSearch(path)` added in T025 to the remaining navigations of
  `frontend/src/pages/library/MediaView.tsx`: the `<Navigate>` to `/all/:id` (N4), `handleMoved`
  (N5), `moveChecked` (N6), `mediaDeleted` (N7), `selectionDeleted` (N8), `selectionMissing` (N9)
  and `folderDeleted` to a parent folder (N10). Navigations that today use `location.pathname`
  become `{ pathname, search }`. Root destinations stay param-free. N1, N2, N3 and N11 are
  already done in T025.
- [X] T035 [US4] Add an optional `returnFocus?: () => HTMLElement | null` prop to
  `frontend/src/ui/DetailSurface.tsx` and pass it to `Drawer` (the existing `Modal.returnFocus`
  pattern). Panel and page ignore it. Add a case to `frontend/src/ui/detail-surface.test.tsx`
  showing that the drawer focuses the returned element on close.
- [X] T036 [US4] Add `focusTargetAfterDetail(id)` to `frontend/src/pages/library/MediaView.tsx`
  (the `[data-detail-id]` card, else the shell `<main>` via `document.querySelector("main")`, the lookup `cardLeaving` already uses):
  - use it in the existing close effect (panel and page);
  - pass `() => focusTargetAfterDetail(selectedId)` through `MediaDetail` to `DetailSurface`
    (drawer);
  - this also covers closing after Delete from the detail (T032 N7 focus). If the nested
    confirmation `Dialog` still leaves focus on `body`, resolve it with the same `returnFocus`
    strategy (the delete dialog's `returnFocus` returns `focusTargetAfterDetail`), with no
    contract change beyond FR-082;
  - reuse the same `main` lookup as `cardLeaving`.
- [X] T037 [US4] Pass `libraryReturn = libraryReturnParam(scope, query)` from
  `frontend/src/pages/library/MediaView.tsx` to `frontend/src/pages/library/MediaDetail.tsx` and
  append `?from=…` to its Publish link (N12).
- [X] T038 [US4] In `frontend/src/pages/publish/usePublishTask.ts`, make `replaceIds` update only
  `posts` on a copy of the current `URLSearchParams`, so `from` survives Continue, Review and
  Results.
- [X] T039 [US4] In `frontend/src/pages/publish/PublishTask.tsx`, resolve "Back to media":
  - read `from` with `parseLibraryReturn`;
  - if valid, go to `libraryViewPath(project.id, scope) + "/" + media.id + search`, rebuilt and
    never the raw value (N13);
  - otherwise keep `/p/:id/library/:mediaId` (N14).
- [X] T040 Run `cd frontend && npx vitest run src/pages/library/search-filters.test.tsx src/pages/publish/publish-page.test.tsx src/pages/publish/usePublishTask.test.tsx src/ui/detail-surface.test.tsx src/pages/library/media-content.test.tsx src/pages/library/media-delete.test.tsx src/routes.test.tsx`; all green.

**⛔ STOP C — Detail, Publish and focus review** (servers running): quickstart scenarios 5 and 6
at 1300, 900 and 375 px:
- the detail opens and closes with the params;
- deep link to a hidden Media;
- edit until the Media no longer matches;
- focus never on `body`;
- Publish → Continue → "Back to media";
- Publish entered from Posts;
- a manipulated `from` in the address bar.

Commit C (`feat: preserve library context across detail and publish`) after approval.

---

## Phase 5: Checkpoint D — Mobile & result UX (US7, US8, US6)

**Goal**: below 768 px:
- search at full width;
- `Filters · N` + Sort on one row;
- scrollable chips;
- the `Sheet` with three radio groups applying changes immediately, plus `Clear filters` and
  `Done`.

At every width: the empty-results matrix with `Clear search`, `Clear filters` and `Search all
media`.

**Independent Test**: the D cases in `search-filters.test.tsx` pass at 375 px and 1300 px.

### Tests for Checkpoint D (write first)

- [X] T041 [P] [US7] Add mobile cases at `setViewport(375)` to
  `frontend/src/pages/library/search-filters.test.tsx`:
  - the search box, the `Filters` button and the Sort select are present, and the desktop
    Type/Usage/Imported selects are not;
  - `Filters` shows `Filters · 2` with the accessible name `Filters, 2 active`;
  - opening the Sheet shows the groups Type, Usage and Imported; choosing a radio updates the URL
    and results immediately;
  - `Clear filters` resets them (disabled when none are active);
  - `Done`, Escape and Close return focus to `Filters`;
  - the chips row is present only with active filters;
  - removing the last chip focuses `Filters`;
  - changing a filter in the Sheet clears an active selection.
- [X] T042 [P] [US8] Add empty-results cases to
  `frontend/src/pages/library/search-filters.test.tsx`:
  - search only → `Clear search` (+ `Search all media` in a folder, not in All media);
  - filters only → `Clear filters` only;
  - both → `Clear search` (primary), `Clear filters` and, in Folder/Unsorted, `Search all
    media`;
  - an empty folder or Unsorted keeps its current message with no search, filters or sort, even
    with params in the URL;
  - the empty Library root keeps its dropzone;
  - only one empty state renders at a time.
- [X] T043 [P] [US6] Add `Search all media` cases to
  `frontend/src/pages/library/search-filters.test.tsx`:
  - from a folder with `q`, filters and sort, it navigates to `/library/all` with the same
    serialized query and shows the matching Media;
  - from Unsorted, the same;
  - not offered without `q`;
  - subfolder entries stay visible and unfiltered while searching (FR-047).

### Implementation for Checkpoint D

- [X] T044 [US7] Add the mobile branch to `frontend/src/pages/library/LibraryFilters.tsx`, chosen
  with the `useMediaQuery(MEDIA_MD_UP)` already used by `MediaView` (only one branch mounted):
  - search at full width;
  - a row with the `Filters` button (`Filters` / `Filters · N`, accessible name per UI copy) and
    the Sort select;
  - the chips row.
- [X] T045 [US7] Add the filters `Sheet` to `frontend/src/pages/library/LibraryFilters.tsx`:
  - `Sheet` from `frontend/src/ui/Dialog.tsx`, titled `Filters`;
  - three vertical `ChoiceGroup` (legends Type, Usage, Imported) from `FILTER_DIMENSIONS`;
  - each change calls `useLibraryQuery.update` immediately;
  - footer with `Clear filters` (disabled without filters) and `Done`;
  - no Apply button.
- [X] T046 [US7] Style the mobile rows in `frontend/src/pages/library/library.css`:
  - search at full width;
  - the `Filters`/Sort row;
  - the chips row with `flex-wrap: nowrap; overflow-x: auto`, without page overflow;
  - keep the persistent chrome to ~1/3 of 667 px.

  Do not constrain the Sheet's height.
- [X] T047 [US8] Create `frontend/src/pages/library/EmptyResults.tsx`:
  - maps `emptyResultsKind` and the scope to `EmptyState` (`headingLevel={2}`, icon `search`);
  - titles and actions per contracts/ui.md §8;
  - `Search all media` as the `secondary` link to `libraryViewPath(all) + search`;
  - in the `both` case, `action` is a fragment with the primary `Clear search` and a secondary
    `Clear filters`.
- [X] T048 [US8] Replace the current "No media match the search and filter." branch in
  `frontend/src/pages/library/MediaView.tsx` with mutually exclusive branches:
  - an empty view keeps its current message;
  - zero results render `<EmptyResults>`;
  - otherwise the grid.

  Subfolder entries stay rendered above (FR-047).
- [X] T049 Run `cd frontend && npx vitest run src/pages/library/search-filters.test.tsx src/pages/library/library.test.tsx`; all green.

**⛔ STOP D — mobile and empty-states review** (servers running): quickstart scenarios 8–10 at
375 and 390 px on a real phone or device emulation:
- persistent chrome ≤ ~1/3 of the height, with the grid dominant;
- no horizontal scroll;
- the Sheet usable at full height;
- chips scroll;
- `Done` returns focus;
- the empty-state matrix;
- `Search all media`.

Commit D (`feat: add mobile library filters and empty results`) after approval.

---

## Phase 6: Checkpoint E — Polish, docs & verification

**Purpose**: responsive verification, regressions, docs, a single round of static checks and
final approval.

- [X] T050 Manual responsive pass at 375, 390, 768, 1024 and 1280 px, with the detail side panel
  open at 1280. Use long titles and filenames (≥ 80 chars, no spaces) and long chip labels.
  Check: no horizontal overflow; two toolbar rows at normal width at 1024 (FR-062); natural
  wrapping with the side panel; readable controls. Fix only CSS in
  `frontend/src/pages/library/library.css`.
- [X] T051 [P] Manual regression pass with active params (quickstart scenario 12):
  - import into a filtered view (the new Media may be hidden; the import panel link opens its
    detail);
  - single and bulk Move/Delete;
  - create, rename and delete folders;
  - breadcrumbs;
  - the empty Library root dropzone.
- [X] T052 [P] Keyboard and screen-reader pass:
  - tab order through search → selects → chips → grid;
  - `Remove filter: …` names;
  - the Sheet traps focus and returns it;
  - the status region announces counts without spamming;
  - "0 selected" is announced after a filter change;
  - focus after closing a detail whose card is gone lands on `main`.
- [X] T053 [P] Update `docs/asset-library.md`:
  - search (accent-insensitive, all words, fields);
  - the Type, Usage (Used = any non-cancelled Post) and Imported filters, combinable;
  - sort;
  - URL params and their reload/share behaviour;
  - the selection-clearing rule;
  - Publish's "Back to media" context;
  - remove the "run in the browser only, local state" wording that no longer holds.
- [X] T054 Run the static checks once: `cd frontend && npm run lint && npm run format:check && npm run build` (`build` includes `tsc -b`), then `git diff --check` at the repo root. Fix and re-run only the failing check.
- [X] T055 Review the full diff once:
  - no backend, API, pagination or extra-dependency changes;
  - `MediaView.tsx` reads the query only through `useLibraryQuery` (no second source of truth);
  - no `useEffect` clears the selection;
  - `parseLibraryReturn` is the only reader of `from`;
  - no leftover `filterMedia`, `LIBRARY_FILTERS` or `ChoiceGroup` import in the toolbar.
- [X] T056 Mark `specs/025-library-search-filters/checklists/requirements.md` and the spec status
  as implemented, and record the closing summary in the feature folder.

**⛔ STOP E — final visual and functional approval by the user**, before the commit and PR.
Commit E (`docs: document library search and filters`, plus any polish) after approval; then
push the branch and open the PR (CI runs the full suites).

---

## Dependencies & Execution Order

### Checkpoint dependencies

- **Setup (T001)** → **A** → **B** → **C** and **D** → **E**.
- A blocks everything: helpers, URL model and `useLibraryQuery`.
- B blocks C and D: `LibraryFilters`, the reduced toolbar and `MediaView` on the URL.
- C and D touch different parts. C covers the navigations, focus and Publish, with
  `MediaView`/`MediaDetail`/`DetailSurface`/publish. D covers the `LibraryFilters` mobile branch,
  `EmptyResults` and the empty branch of `MediaView`. They could run in parallel, but both edit
  `MediaView.tsx` and `search-filters.test.tsx`. The recommended order is C then D to avoid
  conflicts, each with its own STOP.
- E needs A–D.

### Within each checkpoint

Tests first (they must fail), then implementation, then the targeted run, then the STOP, then the
checkpoint commit.

### Critical path

T001 → T002–T007 → T008–T014 → T015 (STOP A) → T016–T020 → T021–T027 → T028 (STOP B) → T029–T033 →
T034–T039 → T040 (STOP C) → T041–T043 → T044–T048 → T049 (STOP D) → T050–T055 → T056 (STOP E).

## Parallel Opportunities

- **A**:
  - T002, T003, T004 and T005 add independent `describe` blocks to the same test file (write
    them in one sitting), and T006 and T007 go to another file, so they can run in parallel.
  - T008 (`usage-indicator.ts`) and T013 (`library-query.ts`) are independent of T009–T012
    (`library-filters.ts`).
- **B**: T016–T019 (new file) are parallel with T020 (`library.test.tsx`). T021–T023
  (`LibraryFilters.tsx`) are parallel with T024 (`LibraryToolbar.tsx`/`LibraryRoot.tsx`); T025
  and T026 come after them.
- **C**: T033 (publish tests) is parallel with T029–T032. T035 (`DetailSurface.tsx`) and T038
  (`usePublishTask.ts`) are parallel with T034.
- **D**: T047 (`EmptyResults.tsx`) is parallel with T044–T046.
- **E**: T051, T052 and T053 are parallel.

### Parallel example — Checkpoint A

```text
T006 + T007  frontend/src/pages/library/library-query.test.ts
T002–T005    frontend/src/pages/library/library-helpers.test.ts
then: T008 usage-indicator.ts ∥ T013 library-query.ts ∥ T009→T012 library-filters.ts → T014 useLibraryQuery.ts
```

## Implementation Strategy

- **MVP = A + B**: on desktop, search, combinable filters, sort, URL state and safe selection are
  usable and shippable as an increment (US1, US2, US3, US5).
- **C** adds context preservation (US4), the main remaining P2 risk.
- **D** adds mobile and the results UX (US6, US7, US8).
- **E** closes the feature.
- One logical commit per checkpoint, after its STOP; no commit per task. One PR at the end.

## Coverage

### User Stories → checkpoints

| Story | Checkpoints | Main tasks |
|---|---|---|
| US1 Search | A, B | T002, T009, T016, T019, T021, T023, T025 |
| US2 Combine filters | A, B | T003, T005, T008, T010, T012, T016, T017, T021, T022, T025, T027 |
| US3 Safe bulk selection | B | T018, T026 |
| US4 Return with context | A, B, C | T006, T007, T013, T014, T016, T025, T029–T039 |
| US5 Sort | A, B | T004, T011, T016, T021 |
| US6 Search all media | D | T043, T047 |
| US7 Mobile | D | T041, T044–T046 |
| US8 Empty states | D | T042, T047, T048 |

### Functional Requirements → tasks

| FR | Tasks |
|---|---|
| FR-001–FR-007 search semantics | T002, T009 |
| FR-008 live results | T016, T025 |
| FR-009 no fuzzy/semantic | T055 (review) |
| FR-010–FR-013 dimensions, AND, type | T003, T005, T010, T012, T016 |
| FR-014–FR-016 Used/Unused | T003, T008 |
| FR-017–FR-018 Imported presets | T003, T010 |
| FR-019 card indicator unchanged | T003 (`isNotUsedYet`), T020 |
| FR-020–FR-024 active filters, Clear all, Clear search | T005, T017, T022 |
| FR-025 (withdrawn) | — (no task, by design) |
| FR-026–FR-030 sort | T004, T011, T016 |
| FR-031–FR-038 URL state | T006, T013, T014, T016, T025 |
| FR-039–FR-042 detail & navigations | T016, T025 (N1–N3, N11), T029, T032, T034 (N4–N10) |
| FR-043–FR-044 Publish | T007, T033, T037–T039 |
| FR-045–FR-050 folders, Search all media | T043, T047, T051 |
| FR-051–FR-056 selection | T018 (incl. frozen Move), T026, T041 |
| FR-057–FR-060 empty states | T042, T047, T048, T025 |
| FR-061–FR-063 desktop | T021, T027, T050 |
| FR-064–FR-069 mobile | T041, T044–T046, T050 |
| FR-070–FR-076 accessibility | T017, T019, T023, T041, T052 |
| FR-077–FR-079 frontend-only, pure logic | T002–T015, T055 |
| FR-080–FR-082 deep link, stops matching, focus | T030, T031, T032 (delete focus), T035, T036 |

### Success Criteria

| SC | Verified by |
|---|---|
| SC-001 accent-free queries | T002, T016 |
| SC-002 find in < 10 s (1.000 Media) | quickstart scenario 1 in T050/STOP B |
| SC-003 < 100 ms per keystroke | T012 memoization + manual check with 1.000 fake Media in T050 |
| SC-004 36 combinations | T003 |
| SC-005 Used + Unused = total | T003 |
| SC-006 URL restore | T016 |
| SC-007 detail/Publish round trips | T016, T029–T033 |
| SC-008 zero bulk actions on hidden Media | T018, T026 |
| SC-009 mobile chrome ≤ ~1/3, no overflow | T046, T050, STOP D |
| SC-010 existing regressions | T001, T020, T028, T040, T051 |

## Risks covered explicitly

| Risk | Tasks |
|---|---|
| URL propagation | Navigation inventory N1–N14; one test each (T016 for N1–N3/N11, T029–T033 for the rest); `withSearch` as the only path (T025, T034); diff review (T055) |
| Selection safety | Derived selection with no effects; Move frozen at press, like Delete (T026); payload assertions for Move/Delete, including back/forward with the picker open (T018) |
| Focus | Card gone → `main` in panel, drawer and page (T030, T031), including after Delete from the detail (T032); `DetailSurface.returnFocus` (T035, T036) |
| Publish return | Closed grammar + rebuilt destination (T007, T013, T039); manipulated values (T033) |
| Mobile saturation | Persistent chrome only, Sheet unconstrained (T046, T050, STOP D) |

## Notes

- No tasks for backend, API, pagination, virtualization, thumbnails, lazy video, recursive folder
  search, tags, AI, new bulk actions or a visible result counter.
- `[P]` tasks touch different files or independent blocks with no dependency on incomplete
  tasks.
- Keep `MediaView.tsx` from growing: new logic lives in `library-filters.ts`,
  `library-query.ts`, `useLibraryQuery.ts`, `LibraryFilters.tsx` and `EmptyResults.tsx`.
