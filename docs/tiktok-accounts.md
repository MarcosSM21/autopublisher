# Connecting TikTok accounts

A runbook for linking AutoPublisher TikTok accounts to real TikTok accounts through the
official **TikTok Login Kit for Desktop**. Part 1 is done **once per machine**. Part 2 is
what you repeat for **every account**.

This runbook only covers **connecting** accounts. Publishing videos is described in
[tiktok-publishing.md](tiktok-publishing.md).

For a summary see the [Connecting TikTok](../README.md#connecting-tiktok) section of the
README.

---

## How it works

TikTok Login Kit for Desktop accepts a **loopback** redirect URI, so the browser comes
back directly to the local backend:

1. **Connect TikTok** opens TikTok's official authorization page in a new tab.
2. You sign in and allow the two requested permissions.
3. TikTok sends the browser to
   `http://127.0.0.1:8000/api/tiktok/oauth/callback?code=…&state=…`. The backend checks the
   answer, exchanges the one-time code (with PKCE) and immediately redirects the tab to a
   **clean result page**, `http://127.0.0.1:8000/api/tiktok/oauth/result?outcome=…`, so the
   code and the `state` never stay in the address bar or the history.
4. The panel in AutoPublisher shows the result by itself (it checks the attempt every two
   seconds). You can close the TikTok tab.

Requested permissions (and nothing else):

- `user.info.basic` — read the account's `open_id`, display name and avatar;
- `video.publish` — needed to publish videos directly (later feature).

`video.upload` is not requested. TikTok's consent page lets you turn off **Post content to
TikTok**; if you do, the connection is rejected (`tiktok_permission_missing`) because both
permissions are required.

The TikTok `open_id` (the same in the token response and in `user/info`) is the account's
identity. The display name and avatar are only shown for reference and may change.

---

## Part 1 — One-time setup

### 1.1 Check the secure credential storage (Linux/Ubuntu)

TikTok tokens are stored only in the system keyring (service `autopublisher.tiktok`); there
is no insecure fallback. Check the backend exactly as for YouTube:

```bash
cd backend
uv run python -c "import keyring; print(keyring.get_keyring())"
```

It must print a secure backend such as `keyring.backends.SecretService.Keyring`. See
[Connecting YouTube](../README.md#connecting-youtube) for details.

### 1.2 Create the TikTok app and its Sandbox

In [TikTok for Developers](https://developers.tiktok.com/):

1. Create an app (an *Individual* app is enough) and, with the selector set to
   **Sandbox**, create a Sandbox. Everything below is done in the Sandbox: it needs no App
   Review.
2. **Basic information** asks for an app icon, a category, a description, a **Terms of
   Service URL**, a **Privacy Policy URL** and, for Desktop, a **Web/Desktop URL**. Use the
   real documents of this repository — [docs/terms-of-service.md](terms-of-service.md) and
   [docs/privacy-policy.md](privacy-policy.md) — and the public repository URL. Never invent
   URLs or domains.
3. **Add products → Login Kit**, platform **Desktop**, and register exactly this redirect
   URI (http, `127.0.0.1`, port 8000, no trailing slash):

   ```text
   http://127.0.0.1:8000/api/tiktok/oauth/callback
   ```

4. **Add products → Content Posting API** and enable **Direct Post**. This is only what
   makes `video.publish` available; no domain or URL prefix verification is needed (that is
   only for `PULL_FROM_URL`, which AutoPublisher does not use).
5. In **Scopes**, check that `user.info.basic` and `video.publish` are listed.
6. In **Sandbox settings → Target users**, add your own TikTok account (sign in and accept
   TikTok's terms). Only target users can authorize a Sandbox app; it can take a while to
   become active.
7. Apply the changes.

### 1.3 Local configuration

Save the Sandbox **client key** and **client secret** in `backend/data/tiktok-app.json`
(or point `AUTOPUBLISHER_TIKTOK_APP_FILE` to another file):

```json
{ "client_key": "<sandbox client key>", "client_secret": "<sandbox client secret>" }
```

An optional `redirect_uri` overrides the default
`http://127.0.0.1:8000/api/tiktok/oauth/callback`; it must be a loopback `http` URI with a
port, identical to the one registered in Login Kit. **Never commit this file**:
`backend/data/` and `tiktok-app*.json` are git-ignored. The client secret is never sent to
the frontend; the panel only learns whether TikTok is configured. The file is read on every
use, so no restart is needed after changing it.

**Port**: the backend must run on the redirect URI's port (8000 by default,
`uv run uvicorn app.main:app`). If it runs on another port, **Connect TikTok** answers
`tiktok_oauth_not_configured` instead of opening a page TikTok could never return to.

**Single process**: run **one** backend process (no `--workers`). Token renewals of an
account are serialized with an in-memory lock that only protects within that process, so a
rotated refresh token is never sent twice. Several workers are not supported.

---

## Part 2 — Connect an account

1. Start the backend and the frontend, and open the TikTok account in its project (the
   account and the project must be active).
2. Click **Connect TikTok** and authorize AutoPublisher in the new tab with a Sandbox
   target user, keeping **both** permissions on.
3. The tab ends on "TikTok account connected"; the panel shows **Connected** with the
   display name and avatar.

While waiting you can reopen the authorization page or **Cancel**. Starting a new attempt
replaces the previous one; an attempt expires after 10 minutes and does not survive a
backend restart.

### Verify

**Verify connection** checks live signals: a usable access token (renewed first if due),
a correct `user/info` answer and the same `open_id`. The display name and avatar are
updated. Permissions are shown **according to TikTok's last authorization or renewal**
(TikTok has no token inspection): `video.publish` is not checked live, and Verify never
publishes anything.

### Reconnect

**Reconnect** (from **Connected** or **Reconnect required**) runs the same authorization
and stores the new credential under a **new reference** before deleting the old one, so a
failure never leaves the account without a working credential. If TikTok returns a
**different** TikTok account, nothing changes until you confirm: the panel shows both
accounts and **Replace** or **Cancel**. Cancelling (or letting it expire) discards the new
authorization and revokes it best-effort. A TikTok account can be linked to only one
account per project (active or not).

---

## Token lifetime and renewal

TikTok's access token lasts about **24 hours**; the refresh token about **365 days**. The
whole credential (both tokens, their expiries, the granted scopes and where they came from)
is one JSON secret in the keyring, the source of truth; SQLite only keeps a reference, the
public identity, the status and an informational copy of the expiries.

Renewal is **on demand** (Verify, Disconnect and, later, publishing): there is no
background job. The access token is renewed when it has **one hour or less** left. If
TikTok is temporarily unavailable, the current token is still used while it has more than
five minutes left. TikTok may **rotate** the refresh token; the returned one always
replaces the stored one. Every renewal is checked: the same `open_id` and both
permissions, otherwise the account needs reconnecting.

The account shows **Reconnect required** only on definitive evidence: the renewable
authorization expired, TikTok rejected the refresh token, a permission is missing, TikTok
reports another account, or the stored credential is gone. Network problems never change
the status.

## Disconnect and revocation

**Disconnect** asks for confirmation, then revokes AutoPublisher's access with TikTok's
official revocation endpoint and deletes the local credential and connection. The account
and its publications are kept, also for inactive accounts and projects. The panel only
claims what TikTok confirmed:

| Result | Meaning |
|---|---|
| *revoked* | TikTok confirmed the revocation; the connection was removed. |
| *already invalid* | TikTok reported the authorization was no longer valid (expired or revoked elsewhere); the connection was removed, but AutoPublisher does not claim it revoked anything. |
| `tiktok_revoke_failed` | TikTok did not confirm (network, rate limit, unexpected answer, missing configuration). Nothing was removed: **Retry**, or **Remove locally without revoking**. |
| `tiktok_credential_missing` | The stored credential is gone, so AutoPublisher cannot revoke. Nothing was removed and TikTok was not contacted; use **Remove locally without revoking**. |
| `credential_store_unavailable` | The keyring is locked or unavailable. Nothing was removed. |

**Remove locally without revoking** asks for a second confirmation, deletes the local
credential and connection and never contacts TikTok, so TikTok **may still have
AutoPublisher authorized**. Remove it by hand in the TikTok app: *Settings and privacy →
Security and permissions → Manage app permissions* (menu names may vary between app
versions).

## Orphaned credentials

When a reconnection replaces a credential, the old reference is recorded in the
`tiktok_credential_orphans` table in the same transaction, and its secret is deleted right
after. If the keyring fails at that moment, the entry stays registered and is deleted
later: at the next backend start and at the start of every connection, Disconnect or local
removal. A reference used by a connection is never deleted and an orphaned credential is
never used.

## Error codes and troubleshooting

| Code | Meaning / what to do |
|---|---|
| `tiktok_oauth_not_configured` | `tiktok-app.json` is missing or invalid, TikTok rejected the app's credentials, or the backend runs on another port than the redirect URI (see 1.3). |
| `tiktok_oauth_callback_invalid` | TikTok's answer was malformed. Start again. |
| `tiktok_oauth_denied` | Access was cancelled on TikTok's page. |
| `tiktok_oauth_provider_error` | TikTok returned an error, e.g. the account is not a Sandbox target user (see 1.2 step 6). |
| `tiktok_token_exchange_failed` | TikTok rejected the code (already used, expired, PKCE or redirect URI mismatch). Start again. |
| `tiktok_permission_missing` | A permission was not granted; the message names it. Connect again with both permissions on. |
| `tiktok_account_already_connected` | That TikTok account is linked to another account of the project; disconnect it there first. |
| `tiktok_oauth_attempt_expired` / `tiktok_oauth_attempt_not_found` / `tiktok_oauth_attempt_not_confirmable` / `tiktok_connection_changed` | The authorization or the account-change confirmation is no longer valid. Start again. |
| `tiktok_reconnect_required` | The authorization expired, was revoked or lost a permission. Click **Reconnect**. |
| `tiktok_identity_mismatch` | TikTok now reports a different account; reconnect to change it explicitly. |
| `tiktok_not_connected` | Verify on an account without a connection. |
| `tiktok_unavailable` | Network problem, TikTok down or rate-limited. Try again later; nothing changed. |
| `tiktok_unexpected_response` | TikTok answered without the expected data. Try again later. |
| `tiktok_revoke_failed` / `tiktok_credential_missing` | See [Disconnect and revocation](#disconnect-and-revocation). |
| `credential_store_unavailable` | The system keyring is locked or unsupported (see 1.1). |
| `internal_error` | An unexpected local error; nothing new was saved and any previous connection is kept. |

Nothing sensitive is ever logged or returned: callback access logs read
`/api/tiktok/oauth/callback?[redacted]`, HTTP client logs redact tokens, the client secret,
codes, verifiers, challenges, `state` and bearer values, and AutoPublisher's own logs only
contain the account id, the outcome and TikTok's `log_id`.
