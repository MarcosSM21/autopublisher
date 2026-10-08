# Connecting Instagram accounts

A runbook for linking AutoPublisher Instagram accounts to real Instagram **Professional**
accounts (Business or Creator) through **Instagram API with Instagram Login**. Part 1 is
done **once per machine**. Part 2 is what you repeat for **every account**.

AutoPublisher only connects accounts in this version; it does not publish to Instagram yet.

For a summary see the [Connecting Instagram](../README.md#connecting-instagram) section of
the README.

---

## How it works

Meta only accepts **HTTPS** redirect URIs for Instagram Login, and AutoPublisher runs
locally without a certificate. So there is no callback server: AutoPublisher uses a
redirect URI on `https://localhost/...` where **nothing listens**.

1. **Connect Instagram** opens Instagram's official authorization page in a new tab.
2. You sign in with the Professional account and allow the two requested permissions.
3. Instagram sends the browser to `https://localhost/autopublisher/instagram/callback?code=…&state=…#_`.
   The browser shows a connection error page — that is expected.
4. Copy the **full address** from that tab's address bar, paste it in AutoPublisher's panel
   and click **Complete connection**.

The pasted address contains a one-time authorization code that is useless without the app
secret, which never leaves the backend. AutoPublisher sends it in the body of a single
request, clears the field immediately and never stores it. The `state` in the address ties
it to the attempt you started (a different, reused or expired address is rejected).

Requested permissions (and nothing else):

- `instagram_business_basic` — read the account's identity;
- `instagram_business_content_publish` — publish later (future feature).

The `permissions` field Meta returns when the code is exchanged may list **more** than
these two: Meta can include permissions the same Instagram account already granted to the
same Meta App earlier (for example `instagram_business_manage_comments`,
`instagram_business_manage_insights` or `instagram_business_manage_messages`). That is
expected. AutoPublisher still requests only the two permissions above, requires both of
them to be present, and does not assume the list contains only those two.

---

## Part 1 — One-time setup

### 1.1 Check the secure credential storage (Linux/Ubuntu)

Instagram tokens are stored only in the system keyring (service `autopublisher.instagram`);
there is no insecure fallback. Check the backend exactly as for YouTube:

```bash
cd backend
uv run python -c "import keyring; print(keyring.get_keyring())"
```

It must print a secure backend such as `keyring.backends.SecretService.Keyring`. See
[Connecting YouTube](../README.md#connecting-youtube) for details.

### 1.2 Create the Meta App

All of this happens in <https://developers.facebook.com/apps> with your own account.

> **The dashboard may not offer Instagram Login.** In some newly created Meta Apps the
> dashboard does not show **API setup with Instagram login** at all and only offers other
> flows or products, such as *API setup with Facebook login* (which needs a Facebook Page
> and different permissions, and is **not** supported by AutoPublisher). AutoPublisher
> needs a Meta App where Instagram Login is officially available and configured: its
> **API setup with Instagram login** page shows an *Instagram app ID* and an *Instagram app
> secret*. If your app does not show it, use a Meta App of yours that does. There is no
> universal fix for this on AutoPublisher's side, and AutoPublisher never tries to work
> around Meta's restrictions.
>
> If you reuse a Meta App that another project already uses, only **add** AutoPublisher's
> redirect URI to its list (keep the existing ones) and never reset its app secret.

1. **Create app** → choose the **Business** app type.
2. **Add product → Instagram** and open **API setup with Instagram login**.
3. In **Set up Instagram business login → Business login settings → OAuth redirect URIs**,
   add:

   ```
   https://localhost/autopublisher/instagram/callback
   ```

   Save. Check whether the dashboard added a trailing slash; the value in your local config
   must match the registered one (AutoPublisher tolerates a trailing slash when it compares
   the pasted address). If Meta refuses the URI, stop here: this setup is not supported.

   This exact URI was accepted by Meta in the real validation of this feature. The field
   accepts several URIs: add this one next to any existing entry (type it, press Enter so
   it becomes its own entry, then save).
4. **App roles → Roles → Instagram testers**: add the Instagram Professional account you
   want to connect. Then, in Instagram, accept the invitation:
   **Settings and activity → Website permissions → Apps and websites → Tester invites**.

   If the account is not a tester (or another role) of the app, Meta may fail on its own
   page or send the browser back with an OAuth error. AutoPublisher then shows
   `instagram_oauth_provider_error` (it never displays Meta's raw error text).
5. Copy the **Instagram App ID** and **Instagram App Secret** shown in
   **API setup with Instagram login** (not the Facebook App ID/secret of the app).

### 1.3 Local configuration

Create `backend/data/instagram-app.json` (or put it anywhere and point
`AUTOPUBLISHER_INSTAGRAM_APP_FILE` to it):

```json
{
  "app_id": "<Instagram App ID>",
  "app_secret": "<Instagram App Secret>",
  "redirect_uri": "https://localhost/autopublisher/instagram/callback"
}
```

- `app_id` must be the numeric Instagram App ID; `redirect_uri` must be `https`, have a host
  and no fragment, and match the registered URI.
- **Never commit this file.** `backend/data/`, `instagram-app*.json` and `meta-app*.json`
  are git-ignored; check with `git status`. No example file with real-looking values is
  provided on purpose.
- The file is read on every operation: adding or fixing it does not require a restart. The
  panel only learns whether it is usable (`oauth_configured`), never its contents.

---

## Part 2 — Connect an account

### 2.1 Make the Instagram account Professional

Only **Professional** accounts can be connected: **Business** or **Creator**. A personal
account fails with `instagram_account_not_professional`. Convert it in the Instagram app:
**Settings and activity → Account type and tools → Switch to professional account**, choose
Business or Creator, and try again.

### 2.2 Connect

1. In a project's *Accounts* view, an active **Instagram** account of an active project
   shows *Not connected* and **Connect Instagram**.
2. Click it, sign in to Instagram in the new tab (Instagram asks for the credentials every
   time on purpose, so you consciously pick the account) and allow access.
3. Instagram sends the browser to `https://localhost/autopublisher/instagram/callback?…`
   and the browser shows a **connection error** ("unable to connect" or similar). That is
   expected: nothing listens there. Copy the full address of that error page, paste it in
   the panel and click **Complete connection**. The attempt is valid for 10 minutes;
   restarting the backend discards it.
4. The panel shows *Connected* with the username, the account type (Business/Creator), the
   **Instagram account ID** (the identity AutoPublisher relies on), the profile picture when
   available and the date the access expires.

Other actions:

- **Verify connection** (only when *Connected* and the account and project are active)
  checks the account against Instagram, updates its username, type and picture, and renews
  the token when allowed.
- **Reconnect** repeats the authorization. With the same Instagram account the credentials
  are replaced; with a different one AutoPublisher shows both accounts (username and ID) and
  waits for **Replace with the new account** or **Keep current account**.
- **Disconnect** deletes the stored token and the local link (see revocation below).
- The same Instagram account cannot be linked to two accounts of the same project (active or
  not); it can be linked in different projects.
- Inactive accounts or projects keep showing their connection and can be disconnected, but
  cannot connect, reconnect or verify until they are reactivated. Deactivating never
  disconnects.

---

## Token lifetime and renewal

- After the authorization AutoPublisher exchanges the code for a short-lived token and
  immediately for a **long-lived token (60 days)**. Only the long-lived token is stored, only
  in the keyring.
- Meta only renews a long-lived token that is **at least 24 hours old and still valid**.
  AutoPublisher renews it when it needs the credential (today: **Verify connection**) and it
  is at least 24 h old. There is no background renewal.
- A token that is not renewed within 60 days expires and can no longer be renewed: the
  account shows **Reconnect required**. The panel shows the expiry date so you can verify
  before it passes.
- After a **Reconnect** (or Disconnect + Connect) Meta may return a token that keeps the
  expiry of an existing authorization instead of a fresh 60 days. AutoPublisher always
  shows the expiry Meta returns (`expires_in`) and never computes its own 60-day date.
- Temporary problems (network, Meta unavailable, rate limits) never change the connection
  status (`instagram_unavailable`). A token rejected by Meta, a withdrawn permission, an
  identity that no longer matches, an account that is no longer Professional or a missing
  secret switch the account to **Reconnect required**.

## Revoking access

**Disconnect** never contacts Meta: Instagram Login has no documented per-connection
revocation. To remove AutoPublisher's access completely, in Instagram open
**Settings and activity → Website permissions → Apps and websites** and remove your app.

## Development Mode, App Review and access levels

- In **Development Mode** with **Standard Access**, the app works for accounts that have a
  role in it (e.g. Instagram testers) — enough for your own accounts.
- Serving Instagram accounts of people without a role in the app requires **Advanced
  Access**, **App Review** and **Business Verification**. That is out of scope:
  AutoPublisher is a local, single-user app where each user creates their own Meta App.
- If Meta asks for App Review or Advanced Access for one of the two permissions even with
  your own tester account, stop: AutoPublisher never tries to bypass Meta's review or
  restrictions.

## Orphaned credentials

If the keyring fails while AutoPublisher replaces or deletes a token, the old entry may stay
behind. It is harmless (the database no longer points to it); delete it with your system's
tools, for example on Linux:

```bash
secret-tool search service autopublisher.instagram
secret-tool clear service autopublisher.instagram username <credential_ref>
```

## Instagram login troubleshooting

- **AutoPublisher's authorization URL uses `force_reauth=true`** on purpose, so you sign in
  consciously with the account to connect. A side effect is that Instagram may **sign you
  out** of the Instagram session already open in that browser.
- **Several logins in a row** can make Instagram block logins temporarily ("We couldn't
  connect to Instagram…" on Instagram's own login page). Confirm any "Was this you?" alert
  in the Instagram app, wait a few minutes and try again.
- A **private/incognito window** makes it easier to sign in with the right account without
  touching your normal Instagram session. Open AutoPublisher in that same window and start
  **Connect Instagram** from there, so the Instagram tab belongs to the same window.
- If, after signing in, Instagram lands on its home feed instead of the authorization
  screen (for example after a "Save your login info?" prompt — choose **Not now**), go back
  to AutoPublisher, click **Cancel** and **Connect Instagram** again: with the session
  already open, Instagram usually goes straight to the authorization screen.
- Possible future UX improvement (not changed in this feature): reconsider
  `force_reauth=true` because of the sign-out side effect.

## Error codes and troubleshooting

| Code | Meaning / what to do |
|---|---|
| `instagram_oauth_not_configured` | `instagram-app.json` is missing or invalid (see 1.3). |
| `instagram_oauth_redirect_url_invalid` | The pasted address is not the configured redirect URI or has no `code`/`error`. Copy the full address of the tab Instagram opened. The attempt stays open. |
| `instagram_oauth_state_invalid` | The address belongs to another or an already used attempt. Paste the right one or start again. |
| `instagram_oauth_attempt_expired` | More than 10 minutes passed, a newer attempt was started, or the backend restarted. Start again. |
| `instagram_oauth_denied` | Access was cancelled on Instagram's page. |
| `instagram_oauth_provider_error` | Instagram returned an error, e.g. the account is not a tester of the app (see 1.2 step 4). |
| `instagram_token_exchange_failed` | Meta rejected the code (already used, wrong redirect URI or app secret). Check the config and start again. |
| `instagram_permission_missing` | One of the two permissions was not granted; the message names it. Reconnect and allow everything. |
| `instagram_account_not_professional` | Only Business or Creator accounts; convert the account (see 2.1). |
| `instagram_account_already_connected` | That Instagram account is linked to another account of the project; disconnect it there first. |
| `instagram_reconnect_required` | The access expired, was revoked or lost a permission. Click **Reconnect**. |
| `instagram_identity_mismatch` | Verify found a different Instagram account; reconnect to change it explicitly. |
| `instagram_not_connected` | Verify on an account without a connection. |
| `instagram_unavailable` | Network problem, Meta down or rate-limited. Try again later; nothing changed. |
| `instagram_unexpected_response` | Meta answered without the expected data. Try again later. |
| `credential_store_unavailable` | The system keyring is locked or unsupported (see 1.1). |

Nothing sensitive is ever logged: HTTP client logs redact `access_token`, `client_secret`,
`code`, `state` and bearer tokens, and AutoPublisher's own logs only contain the account id
and the error type.

## Real validation (Feature 008)

The connection was validated against Meta with a real Instagram Professional (Creator)
account that has a role in the Meta App, in Standard Access:

| Check | Result |
|---|---|
| A — Meta accepts `https://localhost/autopublisher/instagram/callback`; the browser shows the expected connection error before copying the address | PASS |
| B — `instagram_business_basic` and `instagram_business_content_publish` granted without App Review | PASS |
| C — real identity shown as *Connected* (username, type, account ID, dates, expiry); opaque reference in SQLite, token only in the keyring | PASS |
| D — the code exchange returns `permissions` containing both required permissions | PASS |

Connect, restart, Verify, Disconnect, Reconnect and a second restart were validated. A real
token renewal was not applicable (the token was less than 24 h old); renewal is covered by
the automated tests. No token, app secret, authorization code, `state`, pasted address or
`Authorization` header was found in SQLite, backend/frontend logs or API responses.
