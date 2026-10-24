# Running AutoPublisher as an installation

This guide explains how to run AutoPublisher permanently on your own Linux computer, as a
user service that starts with your desktop session, and optionally how to use it from a
phone or another device on your home network.

All commands are run from the `backend/` directory of your checkout:

```bash
cd /path/to/autopublisher/backend
uv run python -m app.cli <command>
```

There is no separate `autopublisher` program to install: `uv run python -m app.cli` is the
command line. Run `uv run python -m app.cli --help` to list every command.

## Contents

1. [What this deployment mode is](#what-this-deployment-mode-is)
2. [Requirements](#requirements)
3. [Build the frontend](#build-the-frontend)
4. [Configure the installation](#configure-the-installation)
5. [Set or reset the password](#set-or-reset-the-password)
6. [Install and manage the service](#install-and-manage-the-service)
7. [User session and keyring](#user-session-and-keyring)
8. [Health and diagnostics](#health-and-diagnostics)
9. [Access from other devices (LAN)](#access-from-other-devices-lan)
10. [Using it from a phone](#using-it-from-a-phone)
11. [Automatic publishing requirements](#automatic-publishing-requirements)
12. [Laptops and sleep](#laptops-and-sleep)
13. [Logs](#logs)
14. [Backup](#backup)
15. [Restore](#restore)
16. [Update](#update)
17. [Move to another computer](#move-to-another-computer)
18. [Migrate from the development data](#migrate-from-the-development-data)
19. [If the checkout moves](#if-the-checkout-moves)
20. [File permissions](#file-permissions)
21. [Storage and locking](#storage-and-locking)
22. [Development and installation on the same computer](#development-and-installation-on-the-same-computer)
23. [ARM64 and Raspberry Pi](#arm64-and-raspberry-pi)
24. [Remote access (future)](#remote-access-future)

## What this deployment mode is

- **Single user.** One person, one password. There are no user accounts or roles.
- **Local first.** The database, media and platform configuration stay on your computer.
  Nothing runs in the cloud and AutoPublisher is not a hosted service (SaaS).
- **This computer, and optionally your trusted home network.** By default AutoPublisher
  only listens on `127.0.0.1` (this computer). You can enable access from other devices on
  the same private network.
- **Plain HTTP on the network.** Access from other devices is not encrypted (see
  [Access from other devices](#access-from-other-devices-lan)).
- **Never on the public Internet.** Do not expose AutoPublisher to the Internet in any
  way (router port forwarding, public reverse proxy, tunnels). This is not supported.

One process serves both the web interface and the API on one port (8000 by default), with
the built-in scheduler inside it.

## Requirements

On the computer that runs AutoPublisher (the **host**):

- Linux on x86-64 (this is what has been tested).
- A desktop session (for example Ubuntu Desktop with GNOME) with `systemd --user`.
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) to install the backend dependencies.
- A Secret Service keyring (GNOME Keyring or KWallet), used for account tokens. See
  [Connecting YouTube](../README.md#connecting-youtube) for the keyring details.
- `ffmpeg`/`ffprobe` if you use video metadata and **Remove metadata** (as in development).
- The system clock synchronised over the network (the default on Ubuntu; check with
  `timedatectl`, which should show `System clock synchronized: yes`).
- The computer must be on and awake whenever a scheduled post is due.

Node.js is **not** needed to run AutoPublisher. It is only needed to build the frontend,
which can be done on another machine.

## Build the frontend

The installation serves the compiled frontend from `frontend/dist`. That folder is not in
the repository: build it once, and again after every update.

With Node.js 22+ (on the host or on any other computer with the same checkout):

```bash
cd /path/to/autopublisher/frontend
npm ci
npm run build          # writes frontend/dist
```

If you built it elsewhere, copy the whole `dist` folder to `frontend/dist` on the host, or
to any folder and point the configuration at it with `--frontend-dist` (see below).

The installation never uses the Vite development server. If `index.html` is missing in the
configured folder, `serve` refuses to start with "Frontend build not found at …".

## Configure the installation

Install the backend dependencies (without the development tools):

```bash
cd /path/to/autopublisher/backend
uv sync --frozen --no-dev
```

Create the host configuration. It only takes flags; there is no interactive wizard:

```bash
uv run python -m app.cli configure --data-dir ~/.local/share/autopublisher --no-lan
```

| Flag | Meaning | Default |
|---|---|---|
| `--data-dir PATH` | Where the database, media and platform configuration files live | `~/.local/share/autopublisher` |
| `--port N` | Port on this computer (1024–65535) | `8000` |
| `--lan` / `--no-lan` | Allow other devices on the network | off |
| `--allow-host NAME` | Extra host name accepted in the browser address, e.g. `my-pc.local` (repeatable; replaces the list) | none |
| `--clear-allowed-hosts` | Empty that list | |
| `--frontend-dist PATH` | Use a compiled frontend outside `frontend/dist` | `frontend/dist` of this checkout |

Running `configure` again only changes the flags you pass. It writes
`~/.config/autopublisher/config.toml` (mode 0600) and never touches your data. It prints
the resulting settings; restart the service afterwards to apply them.

**Keep port 8000.** YouTube and TikTok redirect to `http://127.0.0.1:8000/...` after you
sign in. The TikTok redirect URI is read from `tiktok-app.json`, but the YouTube one can
only be changed with the `AUTOPUBLISHER_OAUTH_REDIRECT_URI` environment variable, which
the service does not see. With another port, connecting or reconnecting YouTube from the
service does not work. `configure` warns when the port is not 8000.

The data directory must not be a mount point itself: on an external or second disk, use a
subdirectory inside it.

### Where settings come from

For each data path, the first of these that is set wins:

1. A specific environment override, such as `AUTOPUBLISHER_DB_PATH` or
   `AUTOPUBLISHER_MEDIA_DIR`.
2. `AUTOPUBLISHER_DATA_DIR`.
3. `data_dir` in the host configuration.
4. The default.

The port, LAN access, allowed hosts and frontend folder only come from the host
configuration. The configuration file is `~/.config/autopublisher/config.toml`, or the path
in `AUTOPUBLISHER_CONFIG`.

**Environment overrides are not a supported way to configure the service.** The service
does not see variables set in your shell. `status`, `backup` and `restore` print a banner
with the configuration file, data directory and database they act on, and list every
`AUTOPUBLISHER_*` variable they see ("this command is using environment overrides; the
service does not see them"). `install-service` refuses to run while a path override is
set. Put everything in the host configuration with `configure`.

### What lives where

| Kind | Location | In a backup |
|---|---|---|
| Portable data | `<data_dir>/autopublisher.db`, `<data_dir>/media/projects/`, the platform files (`google-oauth-client.json`, `instagram-app.json`, `threads-app.json`, `tiktok-app.json`, `telegram-app.json`, `media-delivery.json`) | Yes |
| Runtime files | `<data_dir>/tmp/` (upload spooling), `<data_dir>/media/tmp/` | No |
| Host settings | `~/.config/autopublisher/config.toml`, `~/.config/systemd/user/autopublisher.service` | No |
| Host state | `~/.local/state/autopublisher/` (logs, locks) | No |
| Account tokens | The system keyring | No |

Uploads are spooled to `<data_dir>/tmp` on disk, not to `/tmp`, so a large upload does not
fill memory on systems where `/tmp` is a `tmpfs`. There must be enough free space on the
data disk for the file being uploaded.

## Set or reset the password

```bash
uv run python -m app.cli set-password
```

It asks for the new password twice without showing it (12 to 1024 characters).

- **First setup**: run it once after `configure` (if you migrate existing data, restore it
  first: see [Migrate from the development data](#migrate-from-the-development-data)).
- **Forgotten password**: run the same command on the host. There is no e-mail or online
  reset; anyone who can run commands as your user on the host can reset it.
- It signs out every browser and device. They must sign in again with the new password.
- It can run while the service is running.

To change the password from the browser, use **Settings → Sign-in → Change password**
(other devices are signed out).

Browser sessions last up to 30 days, and end after 7 days without use. They survive
restarts of the service. After 5 failed sign-in attempts from one device within 15
minutes, further attempts are refused for a while.

## Install and manage the service

```bash
uv run python -m app.cli install-service
```

It refuses to run until the host configuration and the password exist, and while an
`AUTOPUBLISHER_*` path override is set in your shell. It also needs `backend/.venv` (from
`uv sync --frozen --no-dev`).

It writes `~/.config/systemd/user/autopublisher.service`, runs
`systemctl --user daemon-reload` and **enables** the service so that it starts with your
desktop session. It does **not** start it now. Use `--no-enable` to only write the unit.

The unit runs `<checkout>/backend/.venv/bin/python -m app.cli serve` from
`<checkout>/backend`. It does not need `uv` at run time.

```bash
systemctl --user start autopublisher        # start now
systemctl --user status autopublisher       # is it running?
systemctl --user restart autopublisher      # after configure or an update
systemctl --user stop autopublisher         # stop it
journalctl --user -u autopublisher -e       # its recent output
```

Then open `http://127.0.0.1:8000` on the host and sign in.

If it crashes, systemd restarts it after 5 seconds (at most 5 times in 5 minutes). A
configuration problem (no configuration, no password, no frontend build) stops it without
retrying: check `journalctl --user -u autopublisher -e`, fix it and start it again.

To remove the service (your data and configuration are kept):

```bash
uv run python -m app.cli uninstall-service
```

## User session and keyring

This is the most important limitation of this deployment mode.

- The service belongs to your **desktop session**: it starts after you log in and stops
  when you log out. It does not run before login or after logout.
- Account tokens (YouTube, Instagram, Threads, TikTok, Telegram) are in the system keyring.
  **AutoPublisher running does not mean the keyring is unlocked.**
- When you log in with your password, the "Login" keyring is normally unlocked. **Automatic
  login does not reliably unlock it**: the session starts, AutoPublisher starts, but the
  keyring stays locked until you unlock it.
- While the keyring is locked or unavailable, scheduled posts cannot be published. The
  failure is visible on the post, it is retried while its 10-minute window lasts, and then
  the post becomes **Missed**. Nothing is published late.
- Settings → **This installation** shows the secure storage state (`available`, `locked`,
  `unavailable` or `unknown`). Checking it never opens an unlock prompt.
- **Do not remove the keyring password** just so that startup is unattended. That would
  leave every account token readable without a password.

Running without a desktop session (headless server, before login) is not supported. A
headless secret store is future work.

## Health and diagnostics

**Public**: `http://127.0.0.1:8000/health` returns only `{"status":"ok"}` or
`{"status":"degraded"}` (the database does not answer or the scheduler is not running).
It shows no other details and does not check the keyring.

```bash
curl -s http://127.0.0.1:8000/health
```

**Signed in**: Settings shows automatic publishing (running or paused) and **This
installation**: secure storage state, port, LAN access, the addresses to use from other
devices, and the HTTP warning.

**On the host**:

```bash
uv run python -m app.cli status
```

It prints the configuration in use, the data directory and database, port and LAN access,
whether a server is holding the data, the health result, the keyring state, the network
addresses, the log location and permission warnings. It shows no secrets.

## Access from other devices (LAN)

Access from other devices is **off** by default. To enable it:

```bash
uv run python -m app.cli configure --lan
systemctl --user restart autopublisher
uv run python -m app.cli status        # "Addresses on this network: http://192.168.x.y:8000"
```

To disable it again: `configure --no-lan` and restart.

Type the address with **`http://`**, not `https://`: in LAN mode AutoPublisher only speaks
plain HTTP, so an `https://` address does not load.

### Host firewall

If the host runs a firewall that denies incoming connections, other devices cannot reach
AutoPublisher until you allow its port from your network. AutoPublisher never changes
firewall rules itself; this is host-specific configuration.

Example for **Ubuntu with UFW** (default policy "deny incoming"), allowing only your
trusted home network to reach port 8000 (or the port you configured):

```bash
sudo ufw allow from <LAN_SUBNET> to any port 8000 proto tcp
# e.g. sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp
sudo ufw status
```

- Use your actual trusted LAN subnet (see `ip -4 addr`); `192.168.1.0/24` is only an
  example.
- Do **not** use `sudo ufw allow 8000`: it opens the port to every network the host joins.
- Other distributions and firewalls (firewalld, nftables, …) need their own equivalent rule.

The address is also shown in Settings → **This installation**. If none is detected, find
the host's private address with:

```bash
ip -4 addr
```

and use `http://<that address>:8000`. Settings may also suggest `http://<hostname>.local:8000`;
that name only works on networks and devices that support mDNS, and only after adding it
with `configure --allow-host <hostname>.local` (and a restart).

**What this protects and what it does not:**

- Only use it on your own private, trusted home network. Do not enable it on public or
  shared Wi-Fi (cafés, hotels, offices you do not control).
- The connection is **HTTP, not encrypted**. The password and session protect AutoPublisher
  against other devices and websites using it without signing in.
- They do **not** protect against someone who can read or modify your network traffic
  (sniffing, man-in-the-middle). Such a person could see your content and take over your
  session.
- **Never** open or forward a port on your router to AutoPublisher.

## Using it from a phone

With LAN access enabled, open the address in the phone's browser and sign in. From the
phone you can browse projects, Library, Posts and the calendar, schedule and reschedule,
publish, upload media and use Settings.

Connecting or reconnecting **YouTube** and **TikTok** must be done on the host, at
`http://127.0.0.1:8000`, because those platforms redirect back to `127.0.0.1`. From another
device the app explains this instead of starting the flow.

## Automatic publishing requirements

A scheduled post is only published automatically if, during its window (from its time
until 10 minutes later):

- AutoPublisher is running;
- you are logged in to your desktop session;
- the keyring is unlocked and usable;
- the network works;
- the clock is correct;
- the computer is awake.

If any of these fails during the whole window, the post becomes **Missed** and is never
published late automatically. Use **Reschedule** or **Publish now**.

Scheduled posts survive restarts of the service. Stopping the service during an upload
interrupts it; the attempt is closed as interrupted and is not resumed (for YouTube, check
YouTube Studio as described in the README).

## Laptops and sleep

A sleeping or suspended computer is the same as AutoPublisher being stopped: nothing is
published, and posts due during that time become **Missed**.

If the host should publish unattended while you are logged in, disable automatic suspend
in your system settings (for example GNOME Settings → Power → Automatic Suspend) and keep
the laptop on power. AutoPublisher never changes these settings itself.

## Logs

- **File**: `~/.local/state/autopublisher/logs/autopublisher.log`, rotated at 5 MiB with 5
  old files kept (`autopublisher.log.1` … `.5`). The folder is 0700 and the files 0600.
- **Journal**: `journalctl --user -u autopublisher -e` (add `-f` to follow).

Logs record start and stop (mode, port, LAN, effective paths) and scheduler and
publication events. HTTP access lines are not logged. Passwords, tokens, OAuth codes,
client secrets and session cookies in log messages are redacted with known patterns; this
is defence in depth, not a guarantee for every possible message, so keep the logs private.

**If it does not start**: run `systemctl --user status autopublisher` and
`journalctl --user -u autopublisher -e`. Typical messages: the host configuration does not
exist or is invalid, no password is set, the frontend build is missing, another
AutoPublisher already holds the data directory, or a database migration failed.

## Backup

```bash
uv run python -m app.cli backup                                  # into ~/autopublisher-backups
uv run python -m app.cli backup --output /media/$USER/BackupDisk/autopublisher
```

- It is **online**: the service can keep running.
- The output folder must be outside the data directory. A local or external backup disk is
  a good place; no cloud is needed.
- It writes one `autopublisher-backup-<timestamp>.tar` file only after verifying it.

**Included**: the database (with your password hash), the media files used by your
projects, and the platform configuration files. **Not included**: browser sessions,
keyring tokens, the host configuration, logs, temporary files and media no longer used.

The platform configuration files contain app credentials (client IDs and secrets). **Keep
the backup file private**, like the data directory itself.

Deleted items (Posts, Media, Accounts, Projects, folders) are not in a backup made after
the delete, and there is no Trash: a backup made **before** a delete is the only way to get
it back. Folders and the folder of each Media are part of the database, so they are
backed up and restored as they are; a backup from before folders existed restores with
every Media in **Unsorted**. The backup format did not change.

After a delete, AutoPublisher removes the media files and keyring logins nothing uses any
more. If that can't happen at once (for example the keyring is locked), it is retried at
the next start with the keyring unlocked; a file or login that is already gone counts as
done, and nothing still in use is ever removed.

## Restore

**Stop the service first**:

```bash
systemctl --user stop autopublisher
uv run python -m app.cli restore ~/autopublisher-backups/autopublisher-backup-<timestamp>.tar
```

- It restores into the data directory of the host configuration (printed first).
- It validates the whole file before changing anything (structure, sizes, checksums,
  database integrity, known database version). A damaged or unexpected file is refused
  and nothing is changed.
- It shows a summary and asks you to type `yes`. Use `--yes` to skip the question.
- While the service is running it refuses with "Stop AutoPublisher first".
- The current data directory is kept next to it as `<data_dir>.before-restore-<timestamp>`.
  Delete it once everything works.

After the restore:

- The password is the one stored in the backup. If the backup has none (a backup from
  before installation mode), run `set-password`.
- Every browser must sign in again (sessions are never restored).
- Keyring tokens are not in the backup: on another computer, or if they were removed,
  accounts show **Reconnect needed**. Reconnect them.
- The host configuration (port, LAN, allowed hosts) is not changed.

Then start the service: `systemctl --user start autopublisher`.

### If a restore was interrupted

The restore replaces the data directory with two renames: first the current one becomes
`<data_dir>.before-restore-<timestamp>`, then the validated copy
`.<name>.restore-<timestamp>` (hidden, in the same parent folder) becomes `<data_dir>`.
These two steps are not one atomic operation. If the computer crashes or loses power
exactly between them, `<data_dir>` is missing. To recover, with the service stopped:

1. List the parent folder, for example `ls -la ~/.local/share/`.
2. If `<data_dir>` is missing and `<data_dir>.before-restore-<timestamp>` exists, that is
   your previous, complete data. Put it back:

   ```bash
   mv ~/.local/share/autopublisher.before-restore-<timestamp> ~/.local/share/autopublisher
   ```

3. Delete the leftover hidden `.<name>.restore-<timestamp>` folder, if any, and run the
   restore again.

If only a hidden `.<name>.restore-<timestamp>` folder is left and `<data_dir>` exists, the
restore stopped before changing anything: delete that folder.

## Update

There is no automatic updater.

```bash
cd /path/to/autopublisher/backend
uv run python -m app.cli backup                     # recommended
systemctl --user stop autopublisher
git pull                                            # or update the checkout another way
uv sync --frozen --no-dev
cd ../frontend && npm ci && npm run build && cd ../backend   # or copy a new dist
systemctl --user start autopublisher
curl -s http://127.0.0.1:8000/health
```

Database migrations run automatically at startup. If the service does not come back,
check `journalctl --user -u autopublisher -e`. If a migration failed, restore the backup
you made before the update (with the previous version of the checkout).

## Move to another computer

The host configuration is never moved automatically; configure the new computer on its
own.

1. On the old computer: `uv run python -m app.cli backup`, and copy the `.tar` to the new
   one.
2. On the new computer: clone the repository, `uv sync --frozen --no-dev`, build or copy
   the frontend (see [Requirements](#requirements)).
3. Configure it: `uv run python -m app.cli configure --data-dir ...` (port, LAN as needed).
4. Restore: `uv run python -m app.cli restore <file>.tar`.
5. Only if the backup has no password (from before installation mode):
   `uv run python -m app.cli set-password`.
6. `uv run python -m app.cli install-service` and `systemctl --user start autopublisher`.
7. Reconnect the accounts marked **Reconnect needed** (their tokens were in the old
   computer's keyring), then check Settings and the next scheduled posts.

Stop using the old installation for those accounts once the new one works.

## Migrate from the development data

If you have used AutoPublisher in development, your data is in `backend/data`. Move it
into the installation **before** setting the password, because the restore replaces the
database:

```bash
cd /path/to/autopublisher/backend
# stop the development backend first
uv run python -m app.cli configure --data-dir ~/.local/share/autopublisher --no-lan
AUTOPUBLISHER_DATA_DIR="$PWD/data" uv run python -m app.cli backup
uv run python -m app.cli restore ~/autopublisher-backups/autopublisher-backup-<timestamp>.tar
uv run python -m app.cli set-password
```

**Required step: retire the old data.** After checking that the installation works, stop
using `backend/data` with those accounts, for example:

```bash
mv data data.migrated-<date>
```

Both copies point to the same keyring entries. Disconnecting or reconnecting an account in
one copy can delete or replace the credentials the other copy uses. Never run development
against the old data with those accounts again. Development with a new, empty
`backend/data` is fine.

## If the checkout moves

The unit file contains absolute paths to `backend/.venv/bin/python` and to `backend/` as
its working directory. If you move or re-clone the repository:

```bash
cd /new/path/to/autopublisher/backend
uv sync --frozen --no-dev
uv run python -m app.cli install-service
systemctl --user restart autopublisher
```

`status` warns when the installed service points to another checkout.

## File permissions

New directories (data, tmp, logs, configuration) are created as 0700, so other users
cannot reach anything inside them. The host configuration and log files are 0600, and the
service runs with `UMask=0077`, so the files it creates are private too.

An existing data directory or platform file that other users can read (for example an old
`backend/data`) keeps working, but `status` and the log show a warning with the fix.
AutoPublisher never changes the permissions of existing data itself. To fix them:

```bash
chmod 700 ~/.local/share/autopublisher
chmod 600 ~/.local/share/autopublisher/*.json
```

## Storage and locking

Keep the data directory and `~/.local/state/autopublisher` on a local Linux filesystem
(an internal or directly attached disk). AutoPublisher uses file locks to make sure only
one server, restore or backup uses the data at a time; reliable locking on NFS or other
network filesystems is not guaranteed and not supported.

A second AutoPublisher on the same data directory or database refuses to start.

## Development and installation on the same computer

- The development backend (`uv run uvicorn app.main:app --reload`) has no password and
  only accepts connections from this computer. It uses `backend/data` unless
  `AUTOPUBLISHER_DATA_DIR` is set.
- Both use port 8000: stop the service (`systemctl --user stop autopublisher`) while you
  develop, and start it again afterwards.
- Do not point development at the installation's data directory, and see
  [Migrate from the development data](#migrate-from-the-development-data) about shared
  accounts.

## ARM64 and Raspberry Pi

Nothing in this mode is specific to x86-64, but ARM64 (for example a Raspberry Pi) has
**not been verified** and is not supported yet. Known caveats:

- It needs a desktop session with an unlocked keyring; headless operation is not
  supported.
- Many boards have no real-time clock: until the network time is synchronised after boot,
  the clock may be wrong and scheduled posts may be missed.
- Large uploads need disk space in the data directory and enough memory.
- The frontend can be built on another computer and copied (no Node.js on the board).

## Remote access (future)

Access from outside your home network is not implemented or supported. A private VPN such
as Tailscale may be considered in the future. Until then, do not expose AutoPublisher to
the Internet.
