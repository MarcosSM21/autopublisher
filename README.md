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
YouTube channel with OAuth 2.0 (see [Connecting YouTube](#connecting-youtube)); nothing is
uploaded yet. Accounts of the other platforms only store the identity of a future
connected account.

Each project has a content library: images and videos can be imported (drag & drop or
file picker, many at once), previewed, and given a title, description and hashtags.
Importing content does not publish or schedule it.

From a content, publications can be prepared for one or more active accounts of the
same project, optionally with a date and time, and reviewed in the project's **Queue**.
Scheduling only records the intent: nothing is published yet, and nothing happens
automatically when the scheduled time arrives.

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
- Statuses: `unscheduled` (no date), `scheduled` (a date and time) and `cancelled`.
  Dates are sent with a time zone, stored in UTC to the minute and shown in local time.
- Publications start with the content's title, description and hashtags. Each field can
  be overridden per publication (an empty override is allowed); fields without an
  override always follow the content's current values.
- There can be only one active (unscheduled or scheduled) publication per content and
  account. A cancelled publication stays in the queue as history, does not block new
  ones and can be reactivated when there is no conflict.
- Inactive projects or accounts, and contents whose media file is missing, cannot get
  new publications, be scheduled or be reactivated; their publications can still be
  viewed, unscheduled, edited and cancelled.
- Publications cannot be deleted. Real publishing, platform APIs and the scheduler are
  not implemented yet.

API routes: `GET /api/projects/{id}/publications` (queue),
`POST /api/contents/{id}/publications` (one per account), `GET` and `PATCH
/api/publications/{id}`, and `POST /api/publications/{id}/cancel` and `/reactivate`.

### Connecting YouTube

A YouTube account can be linked to a real channel through Google's OAuth 2.0 flow in
your browser. AutoPublisher identifies the channel by its channel ID and keeps the
credentials it needs to upload videos later (uploading is not implemented yet).

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
- Videos uploaded from unverified API projects are restricted to private (relevant for
  the future upload feature).

API routes: `GET /api/accounts/{id}/youtube-connection`,
`POST /api/accounts/{id}/youtube-connection/authorize`, `/verify` and `/disconnect`,
`GET /api/youtube/oauth/callback` (opened by the browser), and
`GET /api/youtube/oauth/attempts/{id}` with `POST .../confirm` and `.../cancel`.

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
