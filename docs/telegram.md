# Telegram: user account and channel publishing

A runbook for connecting a **real Telegram user account** and publishing **text posts**,
**single images** and **single MP4 videos** to one **broadcast channel** the account
administers. AutoPublisher talks to Telegram as the user over MTProto, through
[Telethon](https://docs.telethon.dev/) (1.x). It **never uses the Bot API and never needs a
bot**: messages appear in the channel exactly like a post made by hand from that account.

For a summary see the [Telegram](../README.md#connecting-and-publishing-to-telegram)
section of the README.

---

## 1. App credentials (once)

1. Sign in at <https://my.telegram.org> with your phone number and open
   **API development tools**.
2. Create an application (title such as `AutoPublisher`, platform **Desktop**; do not use
   the word "Telegram" in the title). You get an **`api_id`** (a number) and an
   **`api_hash`** (32 hexadecimal characters).
3. Save them as `backend/data/telegram-app.json` (or point
   `AUTOPUBLISHER_TELEGRAM_APP_FILE` to another path):

   ```json
   {"api_id": 12345678, "api_hash": "0123456789abcdef0123456789abcdef"}
   ```

   The `api_hash` is a secret: **never commit it** (`telegram-app*.json` and `data/` are
   git-ignored) and never paste it into chats or issues. The file is read on every use; no
   restart is needed.

## 2. Connecting an account

Create an account with platform **Telegram** in a project, then in its panel:

1. Type the phone number in international format (`+34600000000`) and click **Send code**.
2. Telegram sends a code to your Telegram app. Type it in the panel. **Never forward the
   code or paste it into a Telegram chat**: Telegram invalidates codes shared that way.
3. If the account has two-step verification, type its password.
4. The panel shows **Connected** with the Telegram name, username and user ID.

A login waiting for its code or password lasts 10 minutes and is kept in memory only; if
the backend restarts, start again. Codes and passwords are never stored or logged.

The authorized session is stored **only in the system keyring** (service
`autopublisher.telegram`). SQLite keeps the public identity, a non-secret
`credential_ref` and the chosen channel; no `.session` file is ever written.
Telegram lists the session as **AutoPublisher** in *Settings → Devices*.

- **Verify** checks for real that the session is still authorized for the same user.
  A revoked or expired session shows **Reconnect required**: connect again with the same
  Telegram account (another Telegram account requires **Disconnect** first).
- **Disconnect** first closes the session in Telegram, then deletes it from the keyring and
  removes the connection. If Telegram cannot be reached nothing is deleted (the session
  would stay alive): try again, or end the AutoPublisher session in Telegram (*Settings →
  Devices*) and disconnect again.

## 3. Choosing the channel

**Choose channel** lists only the **broadcast channels** where the account can post
(owner, or administrator with *Post messages*). Groups, supergroups, forums and private
chats are never offered.

Each Telegram account in AutoPublisher has **one** destination channel. It is stored by its
Telegram id (plus an internal access hash that never leaves the backend), so renaming the
channel does not matter. The channel **cannot be changed while the account has Telegram
publications scheduled or publishing**: finish or cancel them first. To publish to another
channel, use another account (each connection has its own session).

## 4. Publishing

- **Text**: **New text post** in the queue. **Image** / **video**: from the content
  library, like the other platforms.
- The message text (or caption) is the description, a blank line and the hashtags; the
  title is not sent. It is sent as plain text, exactly as shown.
- **Publish now** and the scheduler use the same publisher. Telegram's own scheduled
  messages are not used.

| Content | Accepted | Limit |
|---|---|---|
| Text post | any non-empty text | 4096 characters |
| Image (sent as a photo) | JPEG, PNG, WEBP | 10 MB; width + height ≤ 10000; ratio ≤ 20:1; caption ≤ 1024 |
| Video | MP4 only (MOV and WEBM are rejected) | 2000 MB; caption ≤ 1024 |

Lengths are counted as Telegram does (UTF-16: most emoji count as two). Limits are those of
a regular account; Premium limits are not detected. Files are never transcoded or
recompressed by AutoPublisher (Telegram itself recompresses photos, as with a manual post).
Videos are sent as streamable videos named `video.mp4`, never with the original file name;
Telegram generates the preview.

After a confirmed send the attempt keeps the Telegram **message ID**. A link
(`https://t.me/<channel>/<id>`) is saved only for **public** channels; private channels get
no link.

### No duplicates

Every attempt gets a `random_id`, saved before anything is sent. Telegram deduplicates
messages to the same channel by that id and never forgets it.

- A lost answer or `RANDOM_ID_DUPLICATE` (the previous send may still be in progress) makes
  AutoPublisher repeat the **same** send at most twice (after 3 s and 10 s).
- Only Telegram's confirmation with the message ID for that `random_id` marks the
  publication as **Published**.
- Without confirmation the attempt is **uncertain** (`telegram_unconfirmed`): check the
  channel, then confirm before publishing again. The new attempt **reuses the same
  `random_id`**, so Telegram returns the original message instead of posting it twice.
- AutoPublisher never reads or searches the channel's messages.

### Errors

| Code | Meaning |
|---|---|
| `telegram_rate_limited` | FloodWait: Telegram asks to wait N seconds. Waits up to 5 s are respected automatically; longer ones fail and block publishing for that account until they pass. |
| `telegram_reconnect_required` | The session is no longer valid; connect again. |
| `telegram_channel_unavailable` | The channel is gone, not accessible, or the account can no longer post in it. |
| `telegram_text_invalid` / `telegram_media_rejected` | Telegram rejected the text or the file. |
| `telegram_unavailable` | Telegram could not be reached before sending: nothing was published. |
| `telegram_unconfirmed` | Uncertain outcome, see above. |
| `telegram_busy` | Another operation of the same account is using the session; try again in a moment. |

Only one Telegram operation per account runs at a time (publications wait, panel actions
answer `telegram_busy`); different accounts are independent.

## 5. Limitations (V1)

- One broadcast channel per account; no groups, supergroups, forums or private chats.
- One message per publication: no albums, polls, stories or forwarding.
- No remote edit or delete: delete test messages by hand.
- No custom "send as" identity, no Telegram native scheduling (possible future
  improvement), no QR login, no Premium detection, no custom video thumbnails.

## API

`GET /api/accounts/{id}/telegram-connection`;
`POST .../telegram-connection/login/start` (`{"phone"}`), `/login/code` (`{"code"}`),
`/login/password` (`{"password"}`), `/login/cancel`, `/verify`, `/disconnect`;
`GET .../telegram-connection/channels`; `PUT .../telegram-connection/channel`
(`{"channel_id"}`). Publishing uses the shared `text-publications`, `publish-check`,
`publish` and `attempts` routes. No response ever contains the session, the `api_hash`,
the access hash, a code or a password.
