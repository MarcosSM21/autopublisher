# Quickstart — validating Feature 019

Validation guide, not implementation. Follows CLAUDE.md: targeted tests while
implementing; static checks once before the PR; full suites only in PR CI.

## Prerequisites

- Backend: `cd backend && uv sync`; frontend: `cd frontend && npm ci`.
- Local platform configuration as in previous features (no secrets in the repo).
- A project with Ready accounts for at least YouTube, Instagram, TikTok (Direct Post and
  Inbox permissions) and Threads or Telegram, plus one image and one short video.

## Run the app (manual checks)

```bash
cd backend && uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000
cd frontend && npm run dev
```

Check each journey at 375 px, 768 px, 1024–1279 px and ≥1280 px (browser devtools).

## Journeys (spec SC-002)

| # | Steps | Expected |
|---|---|---|
| A | Library → video → `Publish…` → select 3 → Continue → complete details → Schedule → `Schedule 3 posts` | URL gains `?posts=`; 3 Posts "Scheduled · automatic"; visible in Posts → Upcoming. |
| A′ | Same, one destination's account deactivated in another tab before the CTA | "2 scheduled · 1 still a draft"; no navigation; Retry on the failed row. |
| A″ | Same with Now; reload during publishing | Same Posts reconstructed from `?posts=`; per-destination results. |
| B | Continue → `Finish later` → Posts → Drafts → `Continue in Publish` | Review with exactly the confirmed content per destination and provenance. |
| C | Failed (determined) post → `Reschedule` | "Scheduled · automatic", attempts kept. Needs review post → "Check the result first." |
| D | Posts → Calendar → next week → reload → open a Post | Week kept in URL; Published at its publication time; detail opens. |
| E | Media detail → Usage → Published row | Post detail shows the content actually sent. |
| F | Posts → New post → Text post → Continue → Publish now | Same Review/Result as media; `Finish later` + `Continue setup` resumes via `?posts=`. |

## Targeted automated checks (examples)

```bash
cd backend && uv run pytest tests/test_publications_update.py tests/test_asset_usage.py -q
cd frontend && npx vitest run src/pages/publish src/pages/posts
```

Before opening the PR (once): `uv run ruff check . && uv run ruff format --check . && uv run
mypy .` (backend) and `npm run lint && npm run format:check && npm run typecheck && npm run
build` (frontend), plus `git diff --check`. Full `pytest`/`vitest` run in CI.

## Close checkpoints (T068–T075)

Real-browser review on local fake data (isolated database, no platform configured, no
external API calls), at 375, 600, 768, 1024, 1100, 1279, 1280 and 1440 px.

- [X] Zero horizontal document scroll on every 019 route and width (after moving the
      Calendar week to `xl`).
- [X] A (up to Review/CTA; platforms not configured locally), B, C (`Reschedule` dialog
      says it publishes automatically), D (Calendar → Post detail → close keeps
      `week`), E (Media → Usage → Published Post; Telegram shows the current content
      because it records only the text length), F (Text post page and `Continue setup`).
- [X] Keyboard: Library → Media → Publish; Posts → detail; drawer focus trap and Escape;
      focus back to the card/row on close; sticky bars never cover the focus.
- [X] Static checks once (ruff, ruff format, mypy, oxlint, prettier, tsc, build) and
      `git diff --check`; full suites left to PR CI.
- [X] Security/privacy review of the diff: no findings.
- [X] Boundary: no migrations; scheduler, publishers, overview and Reactivate unchanged;
      R6 is the only lifecycle change; nothing from Feature 020.
- [X] FR-076 checksums in Post detail → Technical details: each attempt records the
      checksum of its prepared file (`submitted.file_checksum`); older attempts show none.
- [X] Final corrections: Media/Post detail headings never skip a level on phones; Publish
      task mode shows no project header, status strip or Get started; setup messages
      (api_id/api_hash, docs paths) are shown as human copy leading to Settings.
