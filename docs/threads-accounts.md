# Connecting Threads accounts

A runbook for linking AutoPublisher Threads accounts to real Threads accounts through the
official **Threads API**. Part 1 is done **once per machine**. Part 2 is what you repeat
for **every account**.

This runbook covers connecting, verifying, reconnecting and disconnecting accounts.
Publishing text posts, images and videos is described in
[Publishing to Threads](threads-publishing.md).

For a summary see the [Connecting Threads](../README.md#connecting-threads) section of the
README.

---

## How it works

Meta only accepts **HTTPS** redirect URIs for OAuth, and AutoPublisher runs locally
without a certificate. So there is no callback server: AutoPublisher uses a redirect URI on
`https://localhost/...` where **nothing listens** (the same approach as
[Instagram](instagram-accounts.md)).

1. **Connect Threads** opens Threads' official authorization page in a new tab.
2. You sign in and allow the two requested permissions.
3. Threads sends the browser to `https://localhost/autopublisher/threads/callback?code=…&state=…#_`.
   The browser shows a connection error page — that is expected.
4. Copy the **full address** from that tab's address bar, paste it in AutoPublisher's panel
   and click **Complete connection**.

The pasted address is checked strictly: its scheme, host, port and path must be **exactly**
those of the configured redirect URI (an address that merely starts the same way, such as
`https://localhost.evil.example/...`, is rejected). It contains a one-time authorization
code (valid one hour, single use) that is useless without the app secret, which never
leaves the backend. AutoPublisher sends it in the body of a single request, clears the
field immediately and never stores it. The `state` ties it to the attempt you started.

Requested permissions (and nothing else):

- `threads_basic` — required by every Threads API call; read the account's identity;
- `threads_content_publish` — needed to publish (see
  [Publishing to Threads](threads-publishing.md)).

Replies, insights, search, mentions or deletion are **not** requested.

After the authorization AutoPublisher exchanges the code for a short-lived token, then for
a long-lived one, and confirms with Meta's token inspection (`debug_token`) that the token
is valid, belongs to the same Threads user and holds **both** permissions. If that cannot
be confirmed, the account is not connected. The Threads user ID returned by Meta is the
account's identity; the username is only shown for reference.

---

## Part 1 — One-time setup

### 1.1 Check the secure credential storage (Linux/Ubuntu)

Threads tokens are stored only in the system keyring (service `autopublisher.threads`,
separate from Instagram's); there is no insecure fallback. Check the backend exactly as for
YouTube:

```bash
cd backend
uv run python -c "import keyring; print(keyring.get_keyring())"
```

It must print a secure backend such as `keyring.backends.SecretService.Keyring`. See
[Connecting YouTube](../README.md#connecting-youtube) for details.

### 1.2 Create the Meta App with the Threads use case

1. In <https://developers.facebook.com/apps> create an app (or reuse yours) and add the use
   case **Access the Threads API**.
2. In the use case, enable only `threads_basic` and `threads_content_publish`.
3. In the use case settings, add to **Valid OAuth Redirect URIs**:
   `https://localhost/autopublisher/threads/callback`. Use exactly the URI Meta saves
   (check whether it added a trailing slash) in the local configuration below.
   Dashboard note (observed during the real validation, not an API requirement): after
   typing the URI, press **Enter** so the dashboard registers it; otherwise saving fails
   with "Specify an OAuth redirect URI".
4. **Deauthorize callback URL** and **Data Deletion Requests URL**: AutoPublisher does
   **not** implement these callbacks. Try to save the use case **without** them, if Meta
   allows it. If Meta requires public, working URLs that a local app cannot provide, stop
   and review the architecture: never enter fictitious values, fake endpoints,
   `https://localhost/...` or a tunnel as a workaround.
5. In **App roles → Roles → Add People**, add your Threads account as a **Threads Tester**,
   then accept the invitation in Threads (*Settings → Account → Website permissions →
   Invites*).
6. Copy the **Threads App ID** and **Threads App Secret** shown by the Threads use case —
   not the Instagram or Facebook ones.

### 1.3 Local configuration

Create `backend/data/threads-app.json` (or point `AUTOPUBLISHER_THREADS_APP_FILE` to
another path):

```json
{
  "app_id": "<Threads App ID>",
  "app_secret": "<Threads App Secret>",
  "redirect_uri": "https://localhost/autopublisher/threads/callback"
}
```

- `redirect_uri` must be HTTPS, without query, fragment or user name, and identical to the
  one registered in the app.
- **Never commit this file**: `threads-app*.json` is git-ignored. Check with `git status`.
- The file is read on every operation that needs it; no restart is required. The account
  panel says when it is missing or invalid (`threads_oauth_not_configured`).

---

## Part 2 — Connect an account

1. Create a project and an account with platform **Threads**. The panel shows
   **Not connected** and **Connect Threads**.
2. Click **Connect Threads**, allow access in the new tab, copy the address of the page
   Threads opens and paste it in the panel.
3. The panel shows **Connected** with the username, display name, Threads user ID, access
   expiry, data access expiry (when Meta reports it) and last verification.

Then:

- **Verify connection** checks, read-only, that the credential is still valid, that it
  belongs to the same Threads user and that both permissions are still granted. Nothing is
  created, changed or deleted in Threads.
- **Reconnect** authorizes again. With the same Threads account the credentials are
  replaced; with a different one the panel shows both accounts and asks you to **Replace**
  or **Keep current account** explicitly.
- **Disconnect** deletes the stored token and the local link (see revocation below).
- The same Threads account cannot be linked to two accounts of the same project (active or
  not); it can be linked in different projects. Instagram and Threads connections are
  independent.
- Inactive accounts or projects keep showing their connection and can be disconnected, but
  cannot connect, reconnect or verify until they are reactivated. Deactivating never
  disconnects.

---

## Token lifetime and renewal

- The authorization code is exchanged for a short-lived token (1 hour) and immediately for
  a **long-lived token (60 days)**. Only the long-lived token is stored, only in the
  keyring. Its expiry comes from Meta's `expires_in`; AutoPublisher never computes it.
- Meta only renews a long-lived token that is **at least 24 hours old and still valid**.
  That is Meta's technical condition, not AutoPublisher's renewal policy.
- AutoPublisher's policy: a token is renewed only when AutoPublisher needs it (today:
  **Verify connection** or publishing) **and** it is within its last **7 days**
  (an internal product setting, not a Meta rule) **and** it is at least 24 hours old.
  There is no background or periodic renewal.
- A token that is not renewed before it expires can no longer be renewed: the account shows
  **Reconnect required**. Use **Verify connection** during the last week to renew it.
- After a renewal AutoPublisher inspects the new token with Meta to refresh the confirmed
  permissions and the data access expiry. If that inspection fails temporarily, the new
  token is kept and the last known information stays until the next verification.

### Data access expiry

Meta grants access to a user's data for **90 days**. For **public** profiles each token
renewal extends it; **private** profiles cannot extend it and must authorize again when it
ends. The panel shows the last date Meta reported (`data_access_expires_at`). It is
**informational**: a past date may simply be out of date after a renewal, so it never
switches the account to **Reconnect required** by itself. Only a current answer from Meta
(invalid token, missing permission, definitive rejection) or an expired token does.

## Revoking access

**Disconnect** never contacts Meta: the Threads API documents no per-connection
revocation for apps. To remove AutoPublisher's access completely, in Threads open
**Settings → Account → Website permissions** and remove your app. AutoPublisher then
detects the revocation on the next **Verify connection** (or use) and shows **Reconnect
required**.

## Development Mode and App Review

- In **Development Mode**, Threads testers can grant `threads_basic` and
  `threads_content_publish` without App Review — enough for your own accounts.
- Accounts without a role in the app need App Review and a published app. That is out of
  scope: AutoPublisher is a local, single-user app where each user creates their own app.
- AutoPublisher confirms the granted permissions with `debug_token`, which Meta documents
  for **tester** tokens of the same app. Serving users without a role would require
  revisiting that check.
- If Meta asks for App Review even with your own tester account, stop: AutoPublisher never
  tries to bypass Meta's review or restrictions.

## Orphaned credentials

If the keyring fails while AutoPublisher replaces or deletes a token, the old entry may stay
behind. It is harmless (the database no longer points to it); delete it with your system's
tools, for example on Linux with `secret-tool` (on Ubuntu it comes from the
`libsecret-tools` package, which may not be installed):

```bash
secret-tool clear service autopublisher.threads username <credential_ref>
```

To list the entries without printing any secret, use the `secretstorage` library that
`keyring` already installs (it prints only the opaque references):

```bash
cd backend
uv run python -c "import secretstorage; c = secretstorage.dbus_init(); \
print([i.get_attributes()['username'] for i in \
secretstorage.search_items(c, {'service': 'autopublisher.threads'})])"
```

Compare them with the `credential_ref` values of the `threads_connections` table: any other
entry is an orphan.

## Error codes and troubleshooting

| Code | Meaning / what to do |
|---|---|
| `threads_oauth_not_configured` | `threads-app.json` is missing or invalid (see 1.3). |
| `threads_oauth_redirect_url_invalid` | The pasted address is not exactly the configured redirect URI (scheme, host, port, path) or has no `code`/`error`. Copy the full address of the tab Threads opened. The attempt stays open. |
| `threads_oauth_state_invalid` | The address belongs to another or an already used attempt. Paste the right one or start again. |
| `threads_oauth_attempt_expired` | More than 10 minutes passed, a newer attempt was started, or the backend restarted. Start again. |
| `threads_oauth_attempt_not_found` / `threads_oauth_attempt_not_confirmable` / `threads_connection_changed` | The account-change confirmation is no longer valid. Start again. |
| `threads_oauth_denied` | Access was cancelled on Threads' page. |
| `threads_oauth_provider_error` | Threads returned an error, e.g. the account is not a tester of the app (see 1.2 step 5). |
| `threads_token_exchange_failed` | Meta rejected the code (already used, older than one hour, wrong redirect URI or app secret). Check the config and start again. |
| `threads_permission_missing` | A permission was not granted or Meta did not confirm it; the message names it when known. Reconnect and allow everything. |
| `threads_account_already_connected` | That Threads account is linked to another account of the project; disconnect it there first. |
| `threads_reconnect_required` | The access expired, was revoked or lost a permission. Click **Reconnect**. |
| `threads_identity_mismatch` | Meta now reports a different Threads user; reconnect to change it explicitly. |
| `threads_not_connected` | Verify on an account without a connection. |
| `threads_unavailable` | Network problem, Meta down or rate-limited. Try again later; nothing changed. |
| `threads_unexpected_response` | Meta answered without the expected data. Try again later. |
| `credential_store_unavailable` | The system keyring is locked or unsupported (see 1.1). |
| `internal_error` | An unexpected local error; nothing new was saved and any previous connection is kept. |

Nothing sensitive is ever logged: HTTP client logs redact `access_token`, `input_token`,
`client_secret`, `code`, `state`, bearer tokens and app tokens, and AutoPublisher's own logs
only contain the account id and the error type.

## Notes for publishing (next feature)

What the next feature needs to know, from the research of this one
([research.md §9](../specs/010-threads-oauth-connection/research.md)):

- publishing requires `threads_content_publish`, already requested and verified here;
- media must be on a **publicly reachable** server at the time of the request (the existing
  temporary media delivery can be reused);
- Threads has a publishing quota, to be handled when publishing;
- no profile-type requirement (public/private, verified) was found for publishing.
