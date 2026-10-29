# AutoPublisher

AutoPublisher is a local, single-user web application to organize, schedule and publish
images and videos across multiple social media accounts.

## Tech stack

- **Frontend**: React, TypeScript, Vite
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic
- **Storage**: local SQLite database and local file system for media

## Status

Projects and social media accounts can be created, listed, edited, deactivated and
reactivated. Posts, Media, Accounts, Projects and Library folders can be deleted (see
[Deleting](#deleting)): delete removes the item from AutoPublisher; it does not delete
content already published on platforms. YouTube accounts can be connected to a real
YouTube channel with OAuth 2.0 (see [Connecting YouTube](#connecting-youtube)), and videos
can be published to it on demand (see [Publishing to YouTube](#publishing-to-youtube)) or
automatically at their scheduled time (see [Automatic publishing](#automatic-publishing)).
Instagram accounts can be connected to a real Instagram Professional account (Business or
Creator) with Instagram Login (see [Connecting Instagram](#connecting-instagram)), and
single images and Reels can be published to it on demand or automatically (see
[Publishing to Instagram](#publishing-to-instagram)). Threads accounts can be connected
to a real Threads account with the official Threads API (see
[Connecting Threads](#connecting-threads)), and text posts, single images and single
videos can be published to it on demand or automatically (see
[Publishing to Threads](#publishing-to-threads)). TikTok accounts can be connected to a
real TikTok account with TikTok Login Kit for Desktop (see
[Connecting TikTok](#connecting-tiktok)), and single videos can be published to it as
private posts (Direct Post) or sent to its TikTok inbox to finish there (Upload to Inbox),
on demand or automatically (see [Publishing to TikTok](#publishing-to-tiktok)).
Telegram accounts can be connected to a real Telegram user account (no bot), and text
posts, single images and single MP4 videos can be published to one broadcast channel it
administers, on demand or automatically (see
[Connecting and publishing to Telegram](#connecting-and-publishing-to-telegram)).
Accounts of the other platforms only store the identity of a future connected account.

Each project has its own **Library** of **Media**: images and videos can be imported (drag &
drop or file picker, many at once), organized in **folders**, previewed, searched,
filtered by type and usage, and given a title, caption and hashtags. Each Media shows where it is used, and **Remove
metadata** creates a clean copy without EXIF, GPS, ComfyUI workflows or prompts, which is
then published instead of the original. Importing media does not publish or schedule it.

From a Media, **Publish…** prepares one **Post** per chosen destination (an active
account of the same project) in one task: **Compose** (destinations, a common text,
optional per-destination customization and reusable **destination presets**), then
**Review** (content and platform details per destination, and **When**: now or a
scheduled time). **Text posts** use the same task from **Posts → New post**. Posts are
followed in the project's **Posts** (list, history and calendar).
Scheduling a Post in the app means AutoPublisher publishes it automatically at that time,
as long as it is running then (see [Automatic publishing](#automatic-publishing));
**Publish now** publishes at once.

Each project's **Analytics** shows the metrics of the posts AutoPublisher published, read
with the platforms' official APIs and the permissions already granted: YouTube views,
likes and comments, and Instagram likes and comments. It ranks posts within one account,
summarizes them by content type, shows one media's posts side by side and each post's
evolution, and never compares platforms quantitatively (see [Analytics](#analytics)).

## Using the app

The app is one responsive shell (sidebar on desktop, icon rail on tablets, bottom
navigation on phones) with **Home**, a **project selector**, the project's **Library**,
**Posts** and **Accounts**, and **Settings** (inside **More** on phones). The URL is the
only navigation state, so every view can be bookmarked, reloaded and reached with
Back/Forward:

| URL | View |
|---|---|
| `/` | Home (all projects); `/?project=<id>` shows one project |
| `/p/<id>/library` | Library root: its folders, **Unsorted** and **All media** |
| `/p/<id>/library/folders/<folderId>[/<mediaId>]` | A folder, optionally with a Media open |
| `/p/<id>/library/unsorted[/<mediaId>]` | Media without a folder |
| `/p/<id>/library/all[/<mediaId>]` | Every Media of the project; `/library/<mediaId>` (older links) opens a Media over it |
| `/p/<id>/library/<mediaId>/publish[?posts=<ids>]` | Publish a Media (task); `posts` resumes those Drafts |
| `/p/<id>/posts[/<postId>]` | Posts, optionally with a Post open; `?view=history`, `?view=calendar&week=<monday>`, `?q=`, `?account=` |
| `/p/<id>/posts/new[?posts=<ids>]` | Text post (task); `posts` resumes those Drafts |
| `/p/<id>/accounts` | Accounts; `/accounts/new` adds one, `/accounts/<accountId>` opens one |
| `/settings` | Settings |

- **Home** answers "what needs my attention, and what happens next?": a banner when
  automatic publishing is paused, **Needs attention** (failed or uncertain posts, missed
  times, accounts to reconnect or finish, posts missing details, logins about to expire;
  each with one action that opens where to fix it) or **Everything looks good**, **Up
  next** (the next five scheduled posts) and the projects. Everything comes from
  `GET /api/overview` (`?project_id=` for one project); it never publishes or changes
  anything.
- **Inside a project**, a status strip shows accounts ready, problems (linking to Home
  filtered by the project), the next post and a paused automation; until the project has
  a ready account, media and a first post, a **Get started** checklist offers the next
  step. Both are derived from the real state; nothing is stored.
- **Accounts** shows each account's state in plain words: **Ready**, **Reconnect
  needed**, **Finish setup** (e.g. a Telegram account without a channel), **Not
  connected** or **Inactive**, with at most one action. **Add account** only asks for
  the platform: **Set up <Platform>** creates the account (no handle is typed; the real
  identity is adopted when it connects) and opens it, with the platform's connection
  panel under **Connection & technical details**. **Delete account** removes an account
  and all its Posts (an account that was never connected shows **Discard setup**, the
  same delete). Platforms that are not configured point to
  Settings; X is shown as **Coming soon**.
- **Library** opens on its root: the project's top-level folders, **Unsorted** (Media
  without a folder) and **All media**, each with its count. A folder shows its
  subfolders, a breadcrumb and its own Media. Every Media view is a grid (2 columns on
  phones, up to 6 on wide screens) with an accent-insensitive search, combinable **Type**,
  **Usage** (Used/Unused) and **Imported** filters and **Sort**, all kept in the URL (see
  [docs/asset-library.md](docs/asset-library.md)); **Select** moves or deletes several
  Media at once, and each card's menu offers **Move** and **Delete media**. Each card
  shows one usage indicator (needs attention, next scheduled time, Drafts, Published or
  Not used yet). **Media detail** has
  the preview, **Publish…** (or **Continue publishing** when it has Drafts), the editable
  **Content**, the **Usage** of the Media (its Posts by state, each linking to its Post
  detail) and **File details** (metadata, checksums and **Remove metadata**), its folder
  with **Move**, and **Delete media**.
- **Publish** is a task without the bottom navigation on phones and with its actions in
  a sticky bar. **Continue** saves the chosen destinations as **Drafts** and opens
  **Review**; **Finish later** keeps them as Drafts and returns to Posts, and they can be
  resumed with **Continue in Publish** (or **Continue setup** for a text post) from a
  stable URL. **Schedule** always enables automatic publishing; a TikTok Direct Post
  asks for its declaration once per action. When several destinations are published or
  scheduled at once, each result is shown separately and partial results are kept.
- **Posts** lists, by meaning, what **Needs you** (failed, needs review, missed, needs
  action or scheduled with a known problem), what is **Upcoming** (publishing now, then
  by day) and the **Drafts**; **History** holds the published and cancelled Posts. The
  **Calendar** shows one week (from Monday, in the browser's time zone) as seven columns
  on wide screens and as an agenda by day otherwise, and never shows Drafts or cancelled
  Posts. A scheduled Post can be changed there with **Edit schedule**, and a missed or
  failed one with **Reschedule**, without opening its detail; on wide screens a Post
  scheduled to publish automatically can also be dragged to another day of the week,
  which opens **Edit schedule** with that day and the same time to confirm. **Post detail** shows the state with its next action (for
  example **Retry now**, **Reschedule** and **Move to drafts** for a failed Post, **Check
  result** for an uncertain one, **Publish automatically** for a legacy manual
  schedule), when it goes out, its content (the content that was actually sent, once
  published), platform details, an **Activity** history with **Technical details**, and
  **Cancel post** / **Reactivate** and **Delete post**.
- **Settings** shows whether automatic publishing is running (with **Pause/Resume**) and
  whether each platform integration is **Configured**, **Partially configured**, **Not
  configured** or **Coming soon**, with a short explanation of what is missing. It never
  shows paths, file contents or secrets; integrations are still configured as described
  in the sections below.

The visual language (tokens, components, states, accessibility rules) is documented in
[docs/design-system.md](docs/design-system.md).

## Running AutoPublisher as an installation

Besides the development setup below, AutoPublisher can run permanently on your Linux
computer as a `systemd --user` service that starts with your desktop session: one process
serves the compiled frontend and the API on `http://127.0.0.1:8000`, protected by a
password, with optional access from a phone or other devices on your trusted home network
(plain HTTP). It is still a local, single-user application: it is not a hosted service and
must never be exposed to the Internet.

Setup, the keyring limitation, LAN access, backup/restore, updates and moving to another
computer are described in [docs/deployment.md](docs/deployment.md).

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
The development backend has no password and only accepts connections from this computer.
If the installed service is running, stop it first (`systemctl --user stop autopublisher`):
both use port 8000.
If the port is in use, add `--port 8001` (the frontend dev proxy expects port 8000, so
update `frontend/vite.config.ts` accordingly).

The REST API lives under `/api` (projects, accounts, contents, publications and YouTube
connections).

### Local data

- Data is stored in `backend/data/autopublisher.db`. The `data/` directory and database
  files are git-ignored and must never be committed.
- Set `AUTOPUBLISHER_DATA_DIR` to use another data directory, or
  `AUTOPUBLISHER_DB_PATH` to use another database file, e.g.
  `AUTOPUBLISHER_DB_PATH=/tmp/autopublisher-test.db uv run uvicorn app.main:app`.
- The database is created and migrated automatically on startup. Migrations live in
  `backend/migrations/` and are managed with Alembic:

```bash
uv run alembic upgrade head                                  # apply migrations manually
uv run alembic revision --autogenerate -m "describe change"  # after changing app/models.py
```

Review every generated migration before committing it; a test fails if the models and
the migrations drift apart.

### Library

The project's media are shown as the **Library** (`Content` stays the internal model and
API name). See [docs/asset-library.md](docs/asset-library.md).

- Cards show the Media's name, type and one usage indicator; technical data lives in the
  detail.
- Usage is derived from the publications, never stored: published and awaiting-user
  (TikTok inbox) publications count as used; the cards' counts follow the same visible
  states as Posts.
- Search (title, file name, caption and hashtags) and the `All`/`Images`/`Videos`/`Not
  used yet` filters work on the loaded Library.
- Media detail shows the Usage (Posts by state) and, under **File details**, the file:
  size, dimensions, duration, checksums, the version that will be published, **Inspect
  metadata** and **Remove metadata**.
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
- **Folders** organize the Library logically: up to 5 levels, names unique among
  siblings (ignoring case). Moving a Media between folders, renaming a folder or
  deleting it never moves or deletes a file on disk. Deleting a folder also removes its
  subfolders and moves their Media to Unsorted: no Media is deleted. New imports go to
  the folder being viewed, otherwise to Unsorted. Media from before folders existed are
  in Unsorted.

### Deleting

Posts, Media, Accounts, Projects and Library folders can be deleted. **Delete removes
the item from AutoPublisher. It does not delete content already published on
platforms**, and it never contacts a platform (nothing is revoked or removed remotely).

- Every delete shows one confirmation with what will also disappear, for example the
  Posts of a Media or an account, or the accounts, posts and media of a project. Nothing
  has to be typed.
- **Post**: a scheduled Post will not be published. A Post that is publishing right now
  can't be deleted until it finishes.
- **Media**: also deletes its Posts and, once nothing uses them, its stored file and clean
  copy. Importing the same file again creates a new Media.
- **Several Media**: in a Library view, **Select** up to 500 Media, then **Delete**. One
  confirmation sums up what goes (Media and their Posts); they are all deleted together,
  or none is. If one is busy (a Post publishing, or Remove metadata running), nothing is
  deleted.
- **Account**: also deletes its Posts, its connection and its stored login. The account on
  the platform is not affected. A connection in progress can no longer complete.
- **Project**: deletes everything in it (accounts, posts, media, folders, presets).
  Global settings are not affected.
- **Folder**: see Folders above; Media move to Unsorted.
- A deleted item is gone everywhere (Home, Posts, History, Calendar, Library, Accounts,
  Publish); ids are never reused. There is no Trash: a delete is permanent. The only way
  back is restoring an earlier backup (see
  [Backup](docs/deployment.md#backup)); keyring logins are not in backups.
- If something changed between the confirmation and the delete (for example a new Post
  was added to the Media), nothing is deleted and the updated confirmation is shown.

### Removing metadata

**Remove metadata** (Media detail → File details) makes the Media safe to publish:

- The original file is never modified. When something has to be removed, a sanitized
  copy is stored next to it; when the file was already clean, no copy is made and the
  original is published as is.
- Once sanitized, every later publication (manual or automatic, on every platform) uses
  the clean copy. If the copy is missing or damaged, publishing fails with a clear error
  and **Remove metadata** recreates it; the original is never used as a silent fallback.
- Images (PNG, JPEG, WebP) keep only what is needed to show them (pixels, frames, alpha,
  color profile and the orientation), without recompression. This removes EXIF, GPS,
  XMP, IPTC, comments and AI generation data: ComfyUI `workflow`/`prompt`, `parameters`
  and similar fields.
- Videos (MP4, MOV, WebM) keep their video and audio streams, copied without
  re-encoding; tags (including ComfyUI's JSON comment), chapters and extra tracks are
  removed. This needs `ffmpeg`; without it the action reports it and importing and
  publishing keep working. ExifTool is not used.
- Removing metadata is rejected while the Media is being published.

Known limitations:

- Before AutoPublisher processes an upload, the web framework (Starlette) may buffer it
  in the system temporary directory, so a large file briefly uses that space (or RAM if
  that directory is a `tmpfs`). If needed, start the backend with `TMPDIR` pointing to a
  disk-backed directory, e.g. `TMPDIR=/path/on/disk uv run uvicorn app.main:app`.
- Old QuickTime `.mov` files without an `ftyp` header may be rejected as unsupported.
  Modern MOV files (iPhone, cameras, current editors) are supported.

### Publications

In the app a publication is a **Post**; the API and the model keep the name
`publication`.

- A publication is the intent to publish one content on one account of the same
  project. A content can have many publications; all of them share its single stored
  file.
- Statuses: `unscheduled` (no date), `scheduled` (a date and time), `cancelled`, the
  execution statuses `publishing`, `published` and `failed` (see
  [Publishing to YouTube](#publishing-to-youtube)), and `awaiting_user_action`: the
  execution finished but the platform waits for you to finish the post there (TikTok
  Upload to Inbox, shown as "Ready in TikTok"); it cannot be edited, cancelled nor sent
  again, still counts as active and becomes `published` or `failed` with **Check
  status**. Dates are sent with a time zone,
  stored in UTC to the minute and shown in local time.
- Publications start with the content's title, description and hashtags. Each field can
  be overridden per publication (an empty override is allowed); fields without an
  override always follow the content's current values.
- There can be only one active (unscheduled, scheduled, publishing, awaiting user action
  or failed) publication per content and account. Cancelled and published publications
  stay in Posts → History and do not block new ones; a cancelled one can be
  reactivated when there is no conflict.
- Inactive projects or accounts, and contents whose media file is missing, cannot get
  new publications, be scheduled or be reactivated; their publications can still be
  viewed, unscheduled, edited and cancelled.
- Publications can be deleted (see [Deleting](#deleting)). Only YouTube can be published to, by hand or
  automatically (see [Automatic publishing](#automatic-publishing)).

- A failed publication can be retried, rescheduled (which enables automatic publishing)
  or moved back to drafts; this is the only lifecycle change of Feature 019.

API routes: `GET /api/projects/{id}/publications` (Posts),
`POST /api/contents/{id}/publications` (one per account), `GET` and `PATCH
/api/publications/{id}`, and `POST /api/publications/{id}/cancel` and `/reactivate`.

### Publish

**Publish…** (in Media detail) and **Posts → New post → Text post** open the same task.
It creates one publication per chosen destination with a single, all-or-nothing request,
then reviews them:

1. **Compose — Destinations**: the project's active accounts. An account that already
   has an active publication of this Media offers to add that Draft instead; published
   and cancelled publications do not block a new one. A text post disables the
   destinations that need media ("Needs media").
2. **Compose — Content**: the caption and hashtags, prefilled with the Media's values.
   Only the fields you edit are sent as overrides (an edited empty field is an explicit
   empty override); the others keep following the Media. **Customize** (per
   destination) overrides title (YouTube only), caption and hashtags for that
   destination. Precedence: destination > common > Media.
3. **Continue** creates the Drafts and opens **Review**, whose URL (`?posts=<ids>`) can be
   reloaded or bookmarked. Review shows the content by destination (editable per
   destination or for a chosen set), the **Platform details** of each destination (saved
   automatically) and **When**: **Now** or **Schedule** (one date for all; scheduling
   always enables automatic publishing).
4. The final action (**Publish to N destinations** or **Schedule N posts**) first checks
   every destination and lists what is missing; with several destinations each result is
   shown on its own. **Finish later** leaves the Drafts for later.

If creating fails nothing is created, and the error is shown on the destination or
field to fix, keeping everything typed. Platforms without a publisher say so. There is
no "publish all" outside this task.

**Destination presets** are named sets of accounts of a project (for example "Short
video": YouTube + Instagram + TikTok). They store only the name and the destinations — no
text, dates or platform options. Choosing a preset replaces the current selection with its
usable accounts; inactive accounts and accounts with an active publication of the Media
are skipped and listed in a notice. Applying a preset never changes it. Presets are
managed in Compose: save the selection as a preset, rename it, replace its destinations
with the selection, or delete it (accounts and publications are not affected). Names are
unique per project, ignoring case.

API routes: `POST /api/contents/{id}/publications` also accepts the optional common
overrides `title_override`, `description_override` and `hashtags_override`, and `targets`,
an object keyed by account id with the same three fields (no other fields; keys must be
selected accounts). Omitted or `null` means inherit; `""` and `[]` are explicit empty
overrides. Presets: `GET` and `POST /api/projects/{id}/distribution-presets` (body `name`,
`account_ids`), `PATCH` (replaces the destinations when `account_ids` is given) and
`DELETE /api/distribution-presets/{id}`.

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

### Connecting Instagram

An Instagram account can be linked to a real Instagram **Professional** account (Business
or Creator) through **Instagram API with Instagram Login**, requesting only
`instagram_business_basic` and `instagram_business_content_publish`. Publishing is
described in [Publishing to Instagram](#publishing-to-instagram).

Full runbook (Meta App, tester role, configuration, troubleshooting):
[docs/instagram-accounts.md](docs/instagram-accounts.md).

In short:

1. Create a Meta App of type **Business**, add **Instagram → API setup with Instagram
   login**, register the redirect URI `https://localhost/autopublisher/instagram/callback`
   and add your Instagram account as an **Instagram tester**.
2. Save `backend/data/instagram-app.json` (or point `AUTOPUBLISHER_INSTAGRAM_APP_FILE` to
   it) with `app_id`, `app_secret` and `redirect_uri`. **Never commit it**;
   `instagram-app*.json` and `meta-app*.json` are git-ignored.
3. In the account's panel click **Connect Instagram**, allow access in the new tab, then
   copy the address of the page Instagram opens (it shows a connection error: nothing
   listens on `https://localhost`) and paste it into the panel. Meta only accepts HTTPS
   redirect URIs, so this paste step replaces a local callback server.

The long-lived token (60 days) is stored only in the system keyring (service
`autopublisher.instagram`), never in SQLite, logs or API responses. It is renewed when
needed (Verify) once it is at least 24 h old; a token that expires shows **Reconnect
required**. **Disconnect** deletes the local credentials and never contacts Meta; remove
the app in Instagram (*Settings and activity → Website permissions → Apps and websites*)
to revoke access. Changing to another Instagram account requires an explicit
confirmation, and an Instagram account can be linked to only one account per project.

API routes: `GET /api/accounts/{id}/instagram-connection`,
`POST /api/accounts/{id}/instagram-connection/authorize`, `/verify` and `/disconnect`, and
`POST /api/instagram/oauth/attempts/{id}/complete` (body `{"redirect_url": "..."}`),
`.../confirm` and `.../cancel`.

### Connecting Threads

A Threads account can be linked to a real Threads account through the official **Threads
API**, requesting only `threads_basic` and `threads_content_publish`. Publishing is
described in [Publishing to Threads](#publishing-to-threads).

Full runbook (Threads use case, tester role, configuration, renewal, troubleshooting):
[docs/threads-accounts.md](docs/threads-accounts.md).

In short:

1. Add the **Access the Threads API** use case to a Meta App, register the redirect URI
   `https://localhost/autopublisher/threads/callback` and add your Threads account as a
   **Threads Tester**. AutoPublisher does not implement the Deauthorize or Data Deletion
   callbacks; if Meta requires public URLs for them, stop and review (never use fake URLs or
   tunnels).
2. Save `backend/data/threads-app.json` (or point `AUTOPUBLISHER_THREADS_APP_FILE` to it)
   with the **Threads** `app_id`, `app_secret` and `redirect_uri`. **Never commit it**;
   `threads-app*.json` is git-ignored.
3. In the account's panel click **Connect Threads**, allow access in the new tab, then copy
   the address of the page Threads opens and paste it into the panel. The address must match
   the configured redirect URI exactly.

The long-lived token (60 days) is stored only in the system keyring (service
`autopublisher.threads`), never in SQLite, logs or API responses. The granted permissions
are confirmed with Meta's token inspection before connecting and on every Verify. The token
is renewed only when needed (Verify) during its last 7 days and once it is at least 24 h old;
a token that expires shows **Reconnect required**. **Disconnect** deletes the local
credentials and never contacts Meta; remove the app in Threads (*Settings → Account →
Website permissions*) to revoke access. Changing to another Threads account requires an
explicit confirmation, and a Threads account can be linked to only one account per project.

API routes: `GET /api/accounts/{id}/threads-connection`,
`POST /api/accounts/{id}/threads-connection/authorize`, `/verify` and `/disconnect`, and
`POST /api/threads/oauth/attempts/{id}/complete` (body `{"redirect_url": "..."}`),
`.../confirm` and `.../cancel`.

### Connecting TikTok

A TikTok account can be linked to a real TikTok account through the official **TikTok
Login Kit for Desktop**, requesting only `user.info.basic` and `video.publish`. Publishing
is described in [Publishing to TikTok](#publishing-to-tiktok).

Full runbook (Sandbox, Login Kit, configuration, renewal, Disconnect, troubleshooting):
[docs/tiktok-accounts.md](docs/tiktok-accounts.md).

In short:

1. In TikTok for Developers, create a **Sandbox** with **Login Kit** (Desktop) and the
   redirect URI `http://127.0.0.1:8000/api/tiktok/oauth/callback`, add **Content Posting
   API** with **Direct Post** and the upload flow, and add your TikTok account as a
   Sandbox **target user**.
2. Save `backend/data/tiktok-app.json` (or point `AUTOPUBLISHER_TIKTOK_APP_FILE` to it) with
   the Sandbox `client_key` and `client_secret`. **Never commit it**; `tiktok-app*.json` is
   git-ignored. Run a single backend process on port 8000.
3. In the account's panel click **Connect TikTok** and allow the three permissions
   (`user.info.basic`, `video.publish`, `video.upload`) in the new tab. The tab ends on a
   clean result page and the panel shows **Connected**. `video.upload` only enables
   Upload to Inbox: without it the connection still works for Direct Post, and a
   **Reconnect** that does not grant all three leaves the previous connection unchanged.

The credential (access token of about 24 h, refresh token of about 365 days, granted
scopes) is stored only in the system keyring (service `autopublisher.tiktok`), never in
SQLite, logs or API responses. It is renewed on demand when the access token has one hour
or less left; TikTok may rotate the refresh token. **Verify connection** checks the token
and the account live, while permissions are shown according to TikTok's last
authorization or renewal. **Disconnect** revokes the access in TikTok and only reports a
revocation TikTok confirmed; if it cannot, **Remove locally without revoking** is offered
(then remove AutoPublisher in TikTok's *Manage app permissions*). Changing to another
TikTok account requires an explicit confirmation, and a TikTok account can be linked to
only one account per project.

API routes: `GET /api/accounts/{id}/tiktok-connection`,
`POST /api/accounts/{id}/tiktok-connection/authorize`, `/verify`, `/disconnect` and
`/remove-local`, `GET /api/tiktok/oauth/callback` (TikTok's redirect) and
`/api/tiktok/oauth/result`, `GET /api/tiktok/oauth/attempts/{id}` and
`POST /api/tiktok/oauth/attempts/{id}/confirm` and `.../cancel`.

### Publishing to YouTube

A publication of a **video** for a connected YouTube account can be uploaded to the
channel with **Publish now**. Images cannot be published to YouTube.

1. Open the Post in the project's **Posts** (or publish from the Media) and review its
   title, description and hashtags.
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

### Publishing to Instagram

A publication of a single **image** (feed post) or a single **video** (Reel) for a
connected Instagram account can be published with **Publish now** or automatically by
the same scheduler as YouTube. Full runbook:
[docs/instagram-publishing.md](docs/instagram-publishing.md).

Instagram Login requires Meta to download the media from a public URL, so AutoPublisher
needs a **temporary media storage**: a private S3-compatible bucket (Cloudflare R2
recommended) where each file is copied under a random key and reached by Meta only
through a signed URL that expires by itself. Configure it once in
`backend/data/media-delivery.json` (or `AUTOPUBLISHER_MEDIA_DELIVERY_FILE`; **never commit
it**, `media-delivery*.json` is git-ignored) and add the **mandatory lifecycle rule** on the
dedicated prefix (`autopublisher-tmp/`, delete after 1 day) as a safety net. Anonymous
Quick Tunnels are not supported; no permanent public copy is ever kept.

- The **Instagram options** panel shows the exact caption (description, blank line,
  hashtags; the title is not sent), the **AI-generated** declaration (required, never
  guessed), **Share to feed** for Reels (on by default) and optional **Alt text** for
  images.
- Images are sent as JPEG (PNG/WebP converted in memory, never cropped or resized);
  Reels are checked with `ffprobe` and never transcoded. Problems are reported before
  anything is uploaded.
- `media_publish` is called exactly once. If its answer is uncertain, only the status
  of the original container can settle it: *published* makes the publication
  **Published** (without a link if Meta does not return the post ID), anything else
  requires checking Instagram before publishing again. Recent posts are never searched.
- The temporary copy is deleted only after the result is saved; a failed cleanup only
  adds a warning. Tokens, signed URLs and provider credentials never reach SQLite, logs
  or the browser.
- Every test publishes for real: use harmless content and delete test posts by hand.

API routes: `GET` and `PUT /api/publications/{id}/instagram-options` plus the shared
`publish-check`, `publish` and `attempts` routes.

### Publishing to Threads

A **text post** (no media), a single **image** or a single **video** for a connected
Threads account can be published with **Publish now** or automatically by the same
scheduler. Full runbook: [docs/threads-publishing.md](docs/threads-publishing.md).

- **Posts → New post → Text post** creates publications without content: the text and
  hashtags belong to the publication. Images and videos come from the Library.
- The **Threads options** panel shows the exact text (description, blank line, hashtags;
  the title is not sent), its conservative length (≤ 500, emoji count as several) and
  links (≤ 5), and the optional **Alt text** for images and videos. Threads may use the
  first link as a preview and turn the first hashtag into a topic tag; AutoPublisher
  always sends the text exactly as shown.
- Images: JPEG/PNG sent as they are, static WebP sent as a lossless PNG, animated WebP
  rejected. Videos: checked with `ffprobe`, never transcoded; requirements that cannot be
  checked locally are recorded as delegated to Threads. Images and videos use the same
  temporary media storage as Instagram; text posts never do.
- A container is published only when it is `FINISHED` **and** at least 30 seconds old
  (AutoPublisher's policy after the real validation). `threads_publish` is called at most
  once; an uncertain answer is settled only by the original container read as published,
  otherwise Threads must be checked before publishing again. Recent posts are never
  searched, and links are never built: **Open on Threads** only uses the official
  permalink.
- Every test publishes for real: use harmless content and delete test posts by hand
  (there is no remote delete).

API routes: `POST /api/projects/{id}/text-publications`, `GET` and
`PUT /api/publications/{id}/threads-options`, plus the shared `publish-check`, `publish`
and `attempts` routes.

### Publishing to TikTok

A single **video** for a connected TikTok account is sent from the local file
(`FILE_UPLOAD`) with **Publish now** or automatically by the same scheduler, in one of two
modes chosen per publication (no default; publications created earlier are Direct Post):

- **Direct Post**: AutoPublisher publishes it, with the options and consent below.
- **Upload to Inbox**: **Send to TikTok** uploads it to the account's TikTok inbox (needs
  `video.upload`, no options nor consent; works with a public account). The publication
  becomes **Ready in TikTok** and you finish the post (caption, privacy, sounds…) in
  TikTok's editor; **Check status** asks TikTok once whether you published it. TikTok
  allows at most 5 pending uploads per account in 24 hours.

Full runbook: [docs/tiktok-publishing.md](docs/tiktok-publishing.md). The rest of this
section describes Direct Post.

- **Unaudited client**: only **Only me** (`SELF_ONLY`) posts, and the TikTok account must
  be **private** when posting. TikTok's caps are dynamic and only reported, never
  hard-coded. TikTok considers a tool for your own accounts not acceptable for its audit,
  so public posting is not guaranteed for AutoPublisher.
- The **TikTok** panel reads Creator Info on every opening, shows the preview, the exact
  caption (counted in UTF-16 units, ≤ 2200, never shortened) and the options with no
  preselection: privacy, comments / duet / stitch, commercial content disclosure (Your
  brand / Branded content; Branded content is never available with Only me) and
  **AI-generated: Yes / No**. Publishing requires accepting TikTok's declaration; the
  consent is bound to the exact video digest, caption and options, and **Publish now**
  asks for it again every time.
- The `publish_id` is saved before uploading; the last chunk is sent exactly once after a
  write-ahead and only the status of that `publish_id` decides the result (posts are never
  listed). Private posts are published without a link. Uncertain results are settled by a
  read-only status check or need a manual check of the profile.
- The upload URL and tokens never reach the database, logs, the API or the browser.
- Out of scope: photos, `PULL_FROM_URL`, media delivery, `video.list`, webhooks,
  remote deletion, App Audit, transcoding and covers. Delete test posts and drafts by
  hand.

API routes: `GET` and `PUT /api/publications/{id}/tiktok-options`,
`GET /api/publications/{id}/tiktok-creator-info`,
`POST /api/publications/{id}/tiktok-consent`,
`GET /api/publications/{id}/tiktok-delivery`, plus the shared `publish-check`, `publish`,
`check-status` and `attempts` routes.

### Connecting and publishing to Telegram

A Telegram account is connected as a **real Telegram user account** over MTProto
(Telethon); the Bot API and bots are never used, so messages look exactly like posts made
by hand. Full runbook: [docs/telegram.md](docs/telegram.md).

1. Create an application at <https://my.telegram.org> (*API development tools*) and save
   its `api_id` and `api_hash` as `backend/data/telegram-app.json` (or point
   `AUTOPUBLISHER_TELEGRAM_APP_FILE` to it). **Never commit it**; `telegram-app*.json` is
   git-ignored.
2. In the account's panel type the phone number, then the code Telegram sends to your app
   (never share it in a chat) and, if enabled, the two-step verification password.
3. **Choose channel** lists only broadcast channels where the account can post; each
   account has one channel, which cannot change while it has Telegram publications
   scheduled or publishing.

The session is stored only in the system keyring (service `autopublisher.telegram`), never
in SQLite, logs, API responses or `.session` files. **Verify** checks it for real;
**Disconnect** closes it in Telegram before deleting it.

Text posts (**Posts → New post → Text post**), one JPEG/PNG/WEBP image or one MP4 video with caption are
published with **Publish now** or by the scheduler; the text is the description and
hashtags, sent exactly as shown. Each attempt has a `random_id` saved before sending:
repeats use the same id, only Telegram's confirmation marks it published, and an uncertain
attempt is retried with the same id so Telegram never posts it twice. The message ID is
kept; a link only for public channels. FloodWait over 5 s fails visibly and blocks
publishing until it passes.

API routes: `GET /api/accounts/{id}/telegram-connection`,
`POST .../telegram-connection/login/start`, `/login/code`, `/login/password`,
`/login/cancel`, `/verify`, `/disconnect`, `GET .../channels` and `PUT .../channel`, plus
the shared publication routes.

### Automatic publishing

A local scheduler inside the backend starts scheduled publications by itself when their
time comes, through exactly the same checks and upload as **Publish now**.

- **AutoPublisher must be running**: the development backend or the installed user
  service (see [docs/deployment.md](docs/deployment.md)). There is no cron job or cloud
  component: while AutoPublisher is stopped, you are logged out, the keyring is locked, or
  the computer is off or asleep, nothing is published.
- **Explicit consent.** Only publications with **auto-publish** enabled are started. In
  the app, **Schedule** (in Publish, **Reschedule** or **Edit schedule**) is that consent:
  it always enables automatic publishing, and the confirmation says so. Older Posts
  scheduled without it are shown as **Scheduled · manual** and offer **Publish
  automatically**. Removing the date (**Move to drafts**), cancelling or reactivating
  always leaves the publication with auto-publish disabled.
- **Upgrading is safe.** Publications scheduled before this version stay with auto-publish
  disabled: they were created when a date did not publish anything.
- **10-minute window.** The scheduler checks the database about every 30 seconds and only
  starts a publication between its scheduled time and 10 minutes later (both included).
  If AutoPublisher was not running during that window, the publication stays
  scheduled and is shown as **Missed** in Posts → **Needs you**, with **Reschedule** and
  **Publish now**; it is never published late automatically. A manual schedule whose
  time has passed is also shown as **Missed**.
- **Pause automation / Resume automation** (in **Settings**, the only place with this
  control; Home and each project only show that it is paused) stops or allows new automatic
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

### Analytics

**Project → Analytics** lists every published post with its platform's original metrics, its
last valid update and its refresh state. Full details: [docs/analytics.md](docs/analytics.md).

- **What is read**: YouTube `viewCount`, `likeCount`, `commentCount` (and `dislikeCount` when
  returned) and Instagram `like_count`, `comments_count`. Instagram insights and Threads need
  permissions AutoPublisher does not request; TikTok and Telegram are not supported yet.
- **Honest values**: a metric the platform did not return is "Not available", never 0.
  YouTube engagement is `(likeCount + commentCount) / viewCount`, calculated per reading and
  never stored; no other platform has engagement in this version.
- **No cross-platform comparison**: rankings and content-type medians stay within one
  account; the side-by-side view of a media only aligns likes and comments, with their
  original names, and never totals or orders them.
- **Refresh**: automatically once a day for posts of the last 90 days, or on demand
  (**Refresh**, **Refresh project**; 15-minute cooldown). Publishing always goes first, and
  YouTube analytics uses at most 200 units a day of the general quota, never the upload one.
- **History**: every reading is kept; **Evolution** shows only real readings, with gaps where a
  metric was missing.

API routes: see [contracts/analytics-api.md](specs/027-analytics-performance/contracts/analytics-api.md).

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
(see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). The backend job installs
`ffmpeg` so the video metadata tests run; locally they are skipped without it.
