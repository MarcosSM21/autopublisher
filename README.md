# AutoPublisher

AutoPublisher is a local, single-user web application to organize, schedule and publish
images and videos across multiple social media accounts.

## Tech stack

- **Frontend**: React, TypeScript, Vite
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic
- **Storage**: local SQLite database and local file system for media

## Status

Projects and social media accounts can be created, listed, edited, deactivated and
reactivated. Nothing is ever deleted. YouTube accounts can be connected to a real
YouTube channel with OAuth 2.0 (see [Connecting YouTube](#connecting-youtube)), and videos
can be published to it on demand (see [Publishing to YouTube](#publishing-to-youtube)) or
automatically at their scheduled time (see [Automatic publishing](#automatic-publishing)).
Accounts of the other platforms only store the identity of a future connected account.

Each project has a content library: images and videos can be imported (drag & drop or
file picker, many at once), previewed, and given a title, description and hashtags.
Importing content does not publish or schedule it.

From a content, publications can be prepared for one or more active accounts of the
same project, optionally with a date and time, and reviewed in the project's **Queue**.
A scheduled publication is only published automatically when the user explicitly enables
**auto-publish** for it and AutoPublisher is running at that time; otherwise publishing is
started by hand with **Publish now**.

## Prerequisites

- Git
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm

## Backend

```bash
cd backend
uv sync                                   # install dependencies
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Check it is running: `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
If the port is in use, add `--port 8001` (the frontend dev proxy expects port 8000, so
update `frontend/vite.config.ts` accordingly).

The REST API lives under `/api` (projects, accounts, contents, publications and YouTube
connections).

### Local data

- Data is stored in `backend/data/autopublisher.db`. The `data/` directory and database
  files are git-ignored and must never be committed.
- Set `AUTOPUBLISHER_DB_PATH` to use another file, e.g.
  `AUTOPUBLISHER_DB_PATH=/tmp/autopublisher-test.db uv run uvicorn app.main:app`.
- The database is created and migrated automatically on startup. Migrations live in
  `backend/migrations/` and are managed with Alembic:

```bash
uv run alembic upgrade head                                  # apply migrations manually
uv run alembic revision --autogenerate -m "describe change"  # after changing app/models.py
```

Review every generated migration before committing it; a test fails if the models and
the migrations drift apart.

### Content library

- Imported files are copied into `backend/data/media/projects/<project id>/` with a
  generated name. Set `AUTOPUBLISHER_MEDIA_DIR` to use another directory. Like the
  database, this directory is git-ignored and must never be committed.
- The original files are never modified, moved or deleted; the library keeps working
  if they are moved or removed afterwards.
- Supported formats (detected from the file content, not its extension): JPEG, PNG and
  WebP images; MP4, MOV and WebM videos. Files are stored as they are: no conversion,
  compression or resizing.
- Limits: 2 GiB per file and 100 files per import.
- Each file gets a SHA-256 checksum. Importing a file that already exists in the same
  project (even under another name) is reported as a duplicate and no copy is created.
  The same file can be imported into different projects.
- Video dimensions and duration are read with `ffprobe` when it is installed (for
  example with the `ffmpeg` package). Without it, videos are still imported and those
  fields stay empty. Image dimensions are always read.
- Contents cannot be deleted yet.

Known limitations:

- Before AutoPublisher processes an upload, the web framework (Starlette) may buffer it
  in the system temporary directory, so a large file briefly uses that space (or RAM if
  that directory is a `tmpfs`). If needed, start the backend with `TMPDIR` pointing to a
  disk-backed directory, e.g. `TMPDIR=/path/on/disk uv run uvicorn app.main:app`.
- Old QuickTime `.mov` files without an `ftyp` header may be rejected as unsupported.
  Modern MOV files (iPhone, cameras, current editors) are supported.

### Publications

- A publication is the intent to publish one content on one account of the same
  project. A content can have many publications; all of them share its single stored
  file.
- Statuses: `unscheduled` (no date), `scheduled` (a date and time), `cancelled`, and the
  execution statuses `publishing`, `published` and `failed` (see
  [Publishing to YouTube](#publishing-to-youtube)). Dates are sent with a time zone,
  stored in UTC to the minute and shown in local time.
- Publications start with the content's title, description and hashtags. Each field can
  be overridden per publication (an empty override is allowed); fields without an
  override always follow the content's current values.
- There can be only one active (unscheduled, scheduled, publishing or failed)
  publication per content and account. Cancelled and published publications stay in the
  queue as history and do not block new ones; a cancelled one can be reactivated when
  there is no conflict.
- Inactive projects or accounts, and contents whose media file is missing, cannot get
  new publications, be scheduled or be reactivated; their publications can still be
  viewed, unscheduled, edited and cancelled.
- Publications cannot be deleted. Only YouTube can be published to, by hand or
  automatically (see [Automatic publishing](#automatic-publishing)).

API routes: `GET /api/projects/{id}/publications` (queue),
`POST /api/contents/{id}/publications` (one per account), `GET` and `PATCH
/api/publications/{id}`, and `POST /api/publications/{id}/cancel` and `/reactivate`.

### Connecting YouTube

A YouTube account can be linked to a real channel through Google's OAuth 2.0 flow in
your browser. AutoPublisher identifies the channel by its channel ID and keeps the
credentials it needs to upload videos.

Step-by-step runbook for setting up Google Cloud and connecting more accounts:
[docs/youtube-accounts.md](docs/youtube-accounts.md).

**1. Create a Google Cloud OAuth client** (once):

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project
   and enable **YouTube Data API v3** (*APIs & Services → Library*).
2. In *Google Auth Platform*, configure the consent screen as **External**, add your own
   Google account as a *test user*, and add the scopes
   `https://www.googleapis.com/auth/youtube.readonly` and
   `https://www.googleapis.com/auth/youtube.upload`.
3. In *Clients*, create a client of type **Desktop app** and download its JSON.
4. Save the JSON as `backend/data/google-oauth-client.json`, or anywhere else and point
   `AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE` to it. **Never commit this file**: it
   contains the client secret. `data/`, `client_secret*.json` and
   `google-oauth-client*.json` are git-ignored, and no example file is provided on
   purpose.

The file is read on every operation, so adding or changing it does not require
restarting the backend. Google redirects to
`http://127.0.0.1:8000/api/youtube/oauth/callback`; if the backend runs on another port,
set `AUTOPUBLISHER_OAUTH_REDIRECT_URI` (it must be `http://127.0.0.1:<port>/...` or
`http://[::1]:<port>/...`).

**2. Secure credential storage.** OAuth tokens are stored only in the operating system's
secure credential storage through the `keyring` backend dependency, never in SQLite,
files, logs or API responses. Supported storages: Secret Service (GNOME Keyring or
KWallet) on Linux, Keychain on macOS and Credential Locker on Windows. Plaintext or
unknown `keyring` backends are refused, with no fallback.

On Linux/Ubuntu:

- Ubuntu Desktop includes GNOME Keyring. On other flavours or minimal installs, run
  `sudo apt install gnome-keyring` (or use KWallet with Secret Service on KDE).
- A graphical session with a D-Bus session bus and an unlocked keyring is required
  (the "Login" keyring is unlocked when you log in). Headless sessions (SSH without a
  desktop, servers, containers) are not supported.
- No extra system libraries are needed: `keyring` installs `SecretStorage` and `jeepney`.
- Optional, to inspect the stored entries: `sudo apt install libsecret-tools`
  (`secret-tool`) or `seahorse`.

Check which backend is used with
`uv run python -c "import keyring; print(keyring.get_keyring())"`; it should print a
secure backend such as `SecretService Keyring`. Otherwise connecting fails with
"The system's secure credential storage is not available".

**3. Connect.** In a project's *Accounts* view, YouTube accounts show their connection
status (*Not connected*, *Connected*, *Reconnect required*) and the linked channel
(title and channel ID):

- **Connect** / **Reconnect** opens Google's consent page in a new tab. Google shows the
  consent screen every time on purpose (`prompt=consent`), so AutoPublisher always gets
  a new refresh token, even after a disconnect. If the Google account manages several
  channels, pick the right one in Google's account chooser; AutoPublisher never guesses
  between several channels.
- If the account is already linked to a different channel, the change has to be
  confirmed explicitly. The same channel cannot be linked to two accounts of the same
  project.
- **Verify connection** checks that the stored credentials still work, refreshing them
  without asking you to log in again.
- **Disconnect** deletes the credentials stored by AutoPublisher and the local link. It
  does **not** revoke the permission in Google, because that revocation applies to every
  AutoPublisher connection that uses the same Google account. To remove AutoPublisher's
  access completely, go to <https://myaccount.google.com/connections>, open the app and
  delete its connections.
- Inactive accounts and projects keep showing their connection and can be disconnected,
  but cannot start a new connection until they are reactivated.

Known limitations:

- While the consent screen is in **Testing** mode, Google expires refresh tokens after
  7 days; the account then shows *Reconnect required*. Publish the app ("In production")
  for longer-lived access; an unverified personal app shows a warning on the consent
  screen but works.
- Videos uploaded from unverified API projects are restricted to private (see
  [Publishing to YouTube](#publishing-to-youtube)).
- While a publication of an account is being uploaded, the account cannot be
  reconnected or disconnected.

API routes: `GET /api/accounts/{id}/youtube-connection`,
`POST /api/accounts/{id}/youtube-connection/authorize`, `/verify` and `/disconnect`,
`GET /api/youtube/oauth/callback` (opened by the browser), and
`GET /api/youtube/oauth/attempts/{id}` with `POST .../confirm` and `.../cancel`.

### Publishing to YouTube

A publication of a **video** for a connected YouTube account can be uploaded to the
channel with **Publish now**. Images cannot be published to YouTube.

1. Open the publication in the project's **Queue** and review its title, description
   and hashtags.
2. Set its **YouTube options** and save them:
   - **Privacy**: `private` (default), `unlisted` or `public`.
   - **Made for kids** and **Altered or synthetic content**: must be declared
     explicitly (Yes/No) before publishing; AutoPublisher never guesses them.
   - **Notify subscribers**: `No` by default. It is always sent explicitly, so YouTube's
     own default (notify) is never applied silently.
3. Click **Publish now**. A confirmation shows the title, the real channel (title and
   channel ID), the privacy, the notification choice, the declarations and the file.
   For a scheduled publication it also warns that it is published now, before its date.
4. After confirming, the publication becomes **Publishing** and shows the upload
   progress; the page does not wait for the whole upload. When YouTube returns the video
   ID it becomes **Published**, with an **Open on YouTube** link, the privacy YouTube
   actually applied and its processing status.

What is sent: the title (at most 100 characters, no `<` or `>`) as `snippet.title`, and
the description followed by a blank line and the hashtags (`#tag1 #tag2`) as
`snippet.description` (at most 5000 bytes, no `<` or `>`). Hashtags are not sent as
YouTube tags. No category, tags or `publishAt` are sent. Invalid metadata, missing
declarations, an image, a missing or changed file, an inactive project or account, a
missing connection or a channel that no longer matches the linked one are all reported
before anything is uploaded.

How the upload works:

- It uses YouTube's resumable upload protocol and streams the stored file from disk in
  8 MiB chunks; the file is never copied, changed or loaded into memory as a whole.
- Before uploading, AutoPublisher checks that the credentials still act on the linked
  channel; it never uploads to another channel.
- Network cuts and temporary YouTube errors are retried within the same upload (up to 6
  consecutive failures, exponential backoff, honouring `Retry-After` up to 60 s) and
  resume from the last byte YouTube confirmed. Whole publications are never retried
  automatically.
- Every execution is recorded as an attempt with its progress, result or error, shown in
  the publication's history. Errors use fixed messages (quota exceeded, upload limit,
  permission denied, reconnect required, network error, and so on); Google's raw
  answers, tokens and upload session URLs are never stored, logged or shown.
- Two clicks or two tabs can never start two uploads of the same publication.
- A published publication is a record of the upload: its date, metadata and options can
  no longer be edited, and it cannot be cancelled. Editing or deleting the video on
  YouTube is not supported: do it in YouTube Studio.
- A **failed** publication keeps its error. Its metadata and options can be fixed and
  **Publish now** used again, which creates a new attempt.

**Manual review required.** If something goes wrong after the last part of the video
was sent (or AutoPublisher stops at that moment, or YouTube's answer cannot be saved),
YouTube may have created the video. AutoPublisher then never uploads it again on its
own: the publication shows *Check YouTube Studio* with the channel, title and time of
the attempt. Look for the video in YouTube Studio; publishing that content to that
account again requires confirming that it was not published. If the backend restarts
during an upload, the attempt is closed as interrupted and nothing is resumed.

**Unverified API projects.** YouTube restricts videos uploaded through `videos.insert`
from unverified API projects created after 28 July 2020 to private. AutoPublisher does
not try to work around it: it shows the privacy YouTube actually applied and a warning
when it differs from the requested one. Making uploads public requires passing YouTube's
API audit for your Google Cloud project.

**Quota.** As of 2026-10-07 the official
[`videos.insert` documentation](https://developers.google.com/youtube/v3/docs/videos/insert)
states that each upload costs 1 unit of the *Video Uploads* quota bucket (older versions
listed 1600 units of the general quota). Google may change it; AutoPublisher does not
hard-code it and reports `quota_exceeded` when YouTube says the quota is used up.

To remove test videos, delete them in YouTube Studio: AutoPublisher does not delete
remote videos.

API routes: `GET` and `PUT /api/publications/{id}/youtube-options`,
`GET /api/publications/{id}/publish-check`, `POST /api/publications/{id}/publish` (body
`{"confirm_remote_checked": false}`, answers `202` at once) and
`GET /api/publications/{id}/attempts`.

### Automatic publishing

A local scheduler inside the backend starts scheduled publications by itself when their
time comes, through exactly the same checks and upload as **Publish now**.

- **AutoPublisher must be running.** There is no cron job, system service or cloud
  component: while the backend is stopped, the computer is off or asleep, nothing is
  published.
- **Explicit consent.** Only publications with **auto-publish** enabled are started.
  When scheduling, check *Publish automatically at this time*; the button then reads
  **Schedule & enable auto-publish**. It can also be enabled (with a confirmation) or
  disabled later on a scheduled publication with a future date. Changing the date without
  confirming it again, removing the date, cancelling or reactivating always leaves the
  publication with auto-publish disabled.
- **Upgrading is safe.** Publications scheduled before this version stay with auto-publish
  disabled: they were created when a date did not publish anything.
- **10-minute window.** The scheduler checks the database about every 30 seconds and only
  starts a publication between its scheduled time and 10 minutes later (both included).
  If AutoPublisher was not running during that window, the publication stays
  **Scheduled** and is shown as **Missed automatic publishing window — Publish now or
  reschedule**; it is never published late automatically. A publication without
  auto-publish is never shown as missed.
- **Pause automation / Resume automation** (Queue header) stops or allows new automatic
  starts. It survives restarts, does not stop uploads in progress and does not block
  **Publish now**. Resuming only starts publications still inside their window.
- **Failures.** If the checks fail at the scheduled time (e.g. the channel must be
  reconnected or the file is missing), nothing is uploaded, the publication stays
  scheduled and the reason is shown; it is checked again at most every 2 minutes while
  its window lasts. Once an upload has started, a failure is final: there are no
  automatic retries. The attempt history shows whether each attempt was **Started
  manually** or **Started by scheduler**.
- At most 2 automatic uploads run at the same time (manual ones are not counted);
  publications due at the same time start in order of their scheduled time.

API routes: `GET` and `PUT /api/automation` (`{"paused": true}`); `auto_publish_enabled`
in `POST /api/contents/{id}/publications` and `PATCH /api/publications/{id}`.

Quality checks:

```bash
uv run pytest                             # tests
uv run ruff check .                       # lint
uv run ruff format --check .              # formatting (fix with: uv run ruff format .)
uv run mypy .                             # type checking
```

## Frontend

```bash
cd frontend
npm install                               # install dependencies
npm run dev                               # http://localhost:5173
```

If the port is in use, run `npm run dev -- --port 5174`. The dev server forwards `/api`
requests to the backend at `http://127.0.0.1:8000`, so start the backend first.

Quality checks:

```bash
npm test                                  # tests
npm run lint                              # lint
npm run format:check                      # formatting (fix with: npm run format)
npm run typecheck                         # type checking
npm run build                             # production build
```

## Continuous integration

GitHub Actions runs the same backend and frontend checks on every push and pull request
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
