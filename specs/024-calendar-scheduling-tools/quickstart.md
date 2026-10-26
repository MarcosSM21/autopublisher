# Quickstart — validating Feature 024

Targeted checks only (repository policy: full suites run in PR CI).

## Prerequisites

- Backend dependencies installed (`cd backend && uv sync --locked`), frontend dependencies installed
  (`cd frontend && npm ci`).
- Manual checks use a scratch instance (own `AUTOPUBLISHER_CONFIG`, failing keyring), never the
  real installation's data.

## Automated checks per checkpoint

```bash
# A — backend atomicity
cd backend && uv run pytest tests/test_publications_update_concurrency.py \
  tests/test_publications_update.py tests/test_scheduler_concurrency.py -q

# B–D — frontend
cd frontend && npx vitest run src/pages/posts/calendar.test.ts \
  src/pages/posts/calendar-view.test.tsx src/pages/posts/action-dialog.test.tsx \
  src/pages/posts/posts-data.test.ts

# E — once, before the PR
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm run build
git diff --check
```

(Same commands as `.github/workflows/ci.yml`.)

## Manual scenarios (scratch instance, browser ≥1280 px and a phone-width window)

1. **Quick Reschedule, week view**: a `scheduled_automatic` Post → clock control → *Edit
   schedule* with its date → change the day → confirm → the Post is on the new day, the
   "Next: …" strip shows the new date, focus is on the Post.
2. **Quick Reschedule, agenda / phone**: same with the visible *Edit schedule* button; the
   dialog is a Sheet on a phone.
3. **Missed / Failed**: *Reschedule* opens empty; a past date is rejected inline.
4. **Drag**: drag a Tuesday 18:30 Post to Thursday → valid days outlined, past days marked
   "Can't move here…" → drop → *Edit schedule* with Thursday 18:30 → cancel → nothing changed,
   focus on the Post → drag again → confirm → Post on Thursday.
5. **Same day / invalid day / Escape**: no dialog, no request.
6. **Not draggable**: `missed`, `failed`, `published`, `publishing` items do not start a drag;
   clicking any item still opens its detail.
7. **Race** (covered by automated tests; optional manual): reschedule a Post a few seconds
   after its time while the scheduler runs → either saved (no start) or 409 with the dialog
   message and the Post shown as Publishing.
