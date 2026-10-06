# Connecting YouTube accounts

A runbook for linking AutoPublisher YouTube accounts to real YouTube channels. Part 1 is done
**once per machine**. Part 2 is what you repeat for **every new account**: it takes about one
minute, and the only manual step is Google's consent screen.

For background (scopes, security model, limitations) see the
[Connecting YouTube](../README.md#connecting-youtube) section of the README.

---

## Part 1 — One-time setup

### 1.1 Check the secure credential storage (Linux/Ubuntu)

AutoPublisher stores OAuth tokens only in the system keyring and refuses insecure backends.

```bash
cd backend
uv run python -c "import keyring; print(keyring.get_keyring())"
```

Expected: a secure backend such as `keyring.backends.SecretService.Keyring`. If you see
`fail Keyring` or a plaintext backend:

- install GNOME Keyring (`sudo apt install gnome-keyring`) or use KWallet with Secret Service;
- run AutoPublisher from a desktop session (D-Bus available, keyring unlocked at login).

### 1.2 Create the Google Cloud OAuth client

All of this happens in <https://console.cloud.google.com/> with your own Google account.
No billing or free trial is needed; ignore "Try for free".

1. **Project.** Click **Select a project → New project**, name it `autopublisher-local`, click
   **Create**. Then select it in the project picker.
2. **API.** Search for `YouTube Data API v3`, open it and click **Enable**.
3. **Consent screen.** Go to **☰ → APIs & Services → OAuth consent screen** (this opens
   **Google Auth Platform**) and click **Get started**:
   - App information: name `AutoPublisher Local`, support email = your email;
   - Audience: **External**;
   - Contact information: your email;
   - Finish: accept the policy, then **Continue → Create**.
4. **Test users.** In **Audience**, keep the status **Testing** and, under **Test users**,
   click **Add users**. Add the email of every Google account you will sign in with, then
   **Save**.
5. **Scopes.** In **Data Access → Add or remove scopes → Manually add scopes**, paste:

   ```
   https://www.googleapis.com/auth/youtube.readonly
   https://www.googleapis.com/auth/youtube.upload
   ```

   Click **Add to table → Update → Save**.
6. **Client.** In **Clients → Create client**, choose **Desktop app**, name it
   `AutoPublisher Desktop`, click **Create**, then **Download JSON**. Never copy or share its
   contents.
7. **Install the file**:

   ```bash
   mv ~/Downloads/client_secret_*.json backend/data/google-oauth-client.json
   chmod 600 backend/data/google-oauth-client.json
   git status --short      # the file must NOT appear (backend/data/ is git-ignored)
   ```

   No backend restart is needed: the file is read on every operation.

### 1.3 Check the configuration

With the backend running (`cd backend && uv run uvicorn app.main:app`), for any YouTube
account id:

```bash
curl -s http://127.0.0.1:8000/api/accounts/<account_id>/youtube-connection
```

`"oauth_configured": true` means the setup is complete. If it is `false`, the file is
missing, unreadable or not a *Desktop app* client.

---

## Part 2 — Connecting an account (repeat for each account)

1. Start the app:

   ```bash
   cd backend && uv run uvicorn app.main:app            # http://127.0.0.1:8000
   cd frontend && npm run dev                           # http://localhost:5173
   ```

2. In AutoPublisher, open an **active project** and, in **Accounts**, create (or pick) an
   **active YouTube account**.
3. In that account's YouTube panel, click **Connect**. A Google tab opens.
4. **Manual step (in Google):**
   - choose the Google account or brand channel to link;
   - accept the "Google hasn't verified this app" warning (**Continue**), which is expected
     while the app is in Testing;
   - grant **all** requested permissions.

   Google shows the consent screen on every Connect/Reconnect on purpose: that is how
   AutoPublisher always gets a fresh refresh token.
5. The tab says "YouTube channel connected"; close it. Within about 2 seconds the
   AutoPublisher panel shows **Connected** with the channel title and channel ID.
6. Optional: click **Verify connection**, which should succeed without asking you to log in.

If the new account belongs to a **different Google account**, first add that email as a
test user (step 1.2.4).

### Rules to keep in mind

- The **channel ID** is what identifies the channel. The AutoPublisher account's handle and
  display name are never changed and do not have to match the channel.
- A channel can be linked to only **one account per project**; another project may reuse it.
- If the account is already linked to a different channel, AutoPublisher asks you to
  **confirm the replacement** explicitly.
- If a Google account manages several channels, pick the right one in Google's chooser.
  AutoPublisher refuses to guess when the choice is ambiguous.
- Inactive accounts or projects cannot start a connection; reactivate them first.

---

## Maintenance

| Situation | What to do |
|-----------|------------|
| Panel shows **Reconnect required** | Click **Reconnect** and grant consent again. |
| App in **Testing** mode | Google expires refresh tokens after **7 days**, so expect **Reconnect required** weekly. To avoid it, in **Audience** click **Publish app** (an unverified personal app keeps showing a warning on the consent screen but works). |
| Remove AutoPublisher's link to a channel | Click **Disconnect**. It deletes the stored credentials locally and does **not** contact Google. |
| Remove AutoPublisher's access in Google completely | <https://myaccount.google.com/connections> → the app → **Delete all connections**. This affects **every** AutoPublisher connection that uses that Google account. |
| Rotate the OAuth client | Create a new Desktop client, replace `backend/data/google-oauth-client.json`, then reconnect each account. |

## Troubleshooting

| Message | Cause and fix |
|---------|---------------|
| "YouTube OAuth is not configured" | The client file is missing or invalid. Repeat step 1.2.7 and check with step 1.3. |
| "The system's secure credential storage is not available" | No secure keyring, or it is locked. See step 1.1, unlock the "Login" keyring and retry. |
| "Grant all requested permissions…" | A permission was unchecked on the consent screen. Connect again and grant both. |
| "This Google account has no YouTube channel" | Pick an identity that owns a channel, or create the channel first. |
| "Could not determine which YouTube channel to connect" | Pick a specific brand channel in Google's chooser and retry. |
| "This YouTube channel is already connected to @… in this project" | Disconnect it from that account first, or use another project. |
| Google error "access_denied" or "app not verified/blocked" | The Google account is not a test user. Add it in step 1.2.4. |
| "Could not reach YouTube" | Network problem. Retry; the connection status is not changed. |

## Security checklist

- Never commit `backend/data/` or any `client_secret*.json` (both are git-ignored).
- Never paste tokens, authorization codes or the client JSON into chats, issues or logs.
- Tokens live only in the system keyring (service `autopublisher.youtube`). SQLite stores
  only public channel data and a non-secret reference.
