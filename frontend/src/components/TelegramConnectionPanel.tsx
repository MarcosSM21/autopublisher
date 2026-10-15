import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  cancelTelegramLogin,
  disconnectTelegram,
  getTelegramConnection,
  listTelegramChannels,
  setTelegramChannel,
  startTelegramLogin,
  submitTelegramCode,
  submitTelegramPassword,
  verifyTelegramConnection,
} from "../api.ts";
import {
  TELEGRAM_CONNECTION_STATUS_LABELS,
  type Account,
  type TelegramChannel,
  type TelegramConnection,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

/** Errors after which the backend state changed and must be read again. */
const RELOAD_CODES = [
  "telegram_reconnect_required",
  "telegram_login_not_pending",
  "telegram_identity_mismatch",
  "telegram_not_configured",
];

interface TelegramConnectionPanelProps {
  account: Account;
  projectActive: boolean;
}

function TelegramConnectionPanel({
  account,
  projectActive,
}: TelegramConnectionPanelProps) {
  const [connection, setConnection] = useState<TelegramConnection | null>(null);
  // What the user types is sent once and cleared; it is never kept afterwards.
  const [secretInput, setSecretInput] = useState("");
  const [channels, setChannels] = useState<TelegramChannel[] | null>(null);
  const [selectedChannel, setSelectedChannel] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(
    () =>
      getTelegramConnection(account.id)
        .then(setConnection)
        .catch((caught: unknown) => setError(toApiError(caught).message)),
    [account.id],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Run one action; the panel shows its result or its error. */
  async function run(
    action: () => Promise<TelegramConnection>,
    success: string | null = null,
  ) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      setConnection(await action());
      setNotice(success);
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (RELOAD_CODES.includes(apiError.code)) {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = secretInput.trim();
    setSecretInput("");
    const step = connection?.login?.step;
    if (step === "code") {
      void run(() => submitTelegramCode(account.id, value));
    } else if (step === "password") {
      void run(() => submitTelegramPassword(account.id, value));
    } else {
      void run(() => startTelegramLogin(account.id, value.replace(/\s+/g, "")));
    }
  }

  function cancelLogin() {
    setSecretInput("");
    void run(() => cancelTelegramLogin(account.id));
  }

  async function loadChannels() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const found = await listTelegramChannels(account.id);
      setChannels(found);
      setSelectedChannel(
        connection?.channel?.channel_id ?? found[0]?.channel_id ?? "",
      );
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (RELOAD_CODES.includes(apiError.code)) {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function saveChannel() {
    await run(
      () => setTelegramChannel(account.id, selectedChannel),
      "Channel saved.",
    );
    setChannels(null);
  }

  function disconnect() {
    if (
      !window.confirm(
        "Disconnect this Telegram account? AutoPublisher will close its session in Telegram and delete it.",
      )
    ) {
      return;
    }
    setChannels(null);
    void run(
      () => disconnectTelegram(account.id),
      "Disconnected. AutoPublisher closed its Telegram session and deleted it.",
    );
  }

  if (connection === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading Telegram connection…</p>
    );
  }

  const connectable = account.is_active && projectActive;
  const { status, identity, login, channel } = connection;
  const canLogin =
    connectable && connection.configured && status !== "connected";

  return (
    <div
      className="telegram-connection"
      role="group"
      aria-label={`Telegram connection of ${account.handle}`}
    >
      <span className={`badge connection-${status}`}>
        {TELEGRAM_CONNECTION_STATUS_LABELS[status]}
      </span>
      {identity && (
        <span className="channel">
          <strong>{identity.display_name}</strong>
          {identity.username && (
            <span className="muted">@{identity.username}</span>
          )}
          <span className="muted">
            Telegram user ID: {identity.telegram_user_id}
          </span>
        </span>
      )}
      {connection.last_verified_at && (
        <span className="muted">
          Last verified {formatDate(connection.last_verified_at)}
        </span>
      )}
      {status === "connected" && (
        <span className="muted">
          Channel:{" "}
          {channel ? (
            <strong>{channel.title}</strong>
          ) : (
            "none chosen yet — choose one to publish"
          )}
        </span>
      )}
      {connection.rate_limited_until && (
        <p role="note">
          Telegram asked to wait. Publishing is possible again after{" "}
          {formatDate(connection.rate_limited_until)}.
        </p>
      )}
      {status === "reconnect_required" && (
        <p role="note">
          The Telegram session is no longer valid. Connect the account again
          with the same Telegram account.
        </p>
      )}

      {!connection.configured && (
        <p className="muted" role="note">
          Telegram is not configured. Save your api_id and api_hash from
          my.telegram.org as <code>backend/data/telegram-app.json</code>. See
          docs/telegram.md.
        </p>
      )}
      {!connectable && (
        <p className="muted">
          Reactivate the account (or project) to connect or verify it.
        </p>
      )}

      {canLogin && (
        <form
          className="telegram-login"
          aria-label="Connect Telegram"
          onSubmit={submitLogin}
        >
          {login === null && (
            <label>
              Phone number (international format, e.g. +34600000000)
              <input
                type="tel"
                value={secretInput}
                autoComplete="off"
                onChange={(event) => setSecretInput(event.target.value)}
              />
            </label>
          )}
          {login?.step === "code" && (
            <label>
              Code Telegram sent to {login.phone_hint} (never share it in a
              chat)
              <input
                type="text"
                inputMode="numeric"
                value={secretInput}
                autoComplete="one-time-code"
                onChange={(event) => setSecretInput(event.target.value)}
              />
            </label>
          )}
          {login?.step === "password" && (
            <label>
              Two-step verification password
              <input
                type="password"
                value={secretInput}
                autoComplete="off"
                onChange={(event) => setSecretInput(event.target.value)}
              />
            </label>
          )}
          <div className="actions">
            <button type="submit" disabled={busy || secretInput.trim() === ""}>
              {login === null ? "Send code" : "Continue"}
            </button>
            {login !== null && (
              <button type="button" disabled={busy} onClick={cancelLogin}>
                Cancel
              </button>
            )}
          </div>
        </form>
      )}

      {status !== "not_connected" && (
        <div className="actions">
          {status === "connected" && (
            <>
              <button
                type="button"
                disabled={busy || !connectable}
                onClick={() =>
                  void run(
                    () => verifyTelegramConnection(account.id),
                    "Connection verified.",
                  )
                }
              >
                Verify connection
              </button>
              <button
                type="button"
                disabled={
                  busy || !connectable || connection.channel_change_blocked
                }
                onClick={loadChannels}
              >
                {channel ? "Change channel" : "Choose channel"}
              </button>
            </>
          )}
          <button type="button" disabled={busy} onClick={disconnect}>
            Disconnect
          </button>
        </div>
      )}
      {status === "connected" && connection.channel_change_blocked && (
        <p className="muted" role="note">
          Finish or cancel the pending Telegram publications of this account
          before changing its channel.
        </p>
      )}

      {channels !== null && (
        <div className="telegram-channels">
          {channels.length === 0 ? (
            <p className="muted">
              This Telegram account has no broadcast channel where it can post.
            </p>
          ) : (
            <>
              <label>
                Channel
                <select
                  value={selectedChannel}
                  onChange={(event) => setSelectedChannel(event.target.value)}
                >
                  {channels.map((item) => (
                    <option key={item.channel_id} value={item.channel_id}>
                      {item.title}
                      {item.username ? ` (@${item.username})` : " (private)"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="actions">
                <button
                  type="button"
                  disabled={busy || selectedChannel === ""}
                  onClick={saveChannel}
                >
                  Save channel
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setChannels(null)}
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {notice && (
        <p className="muted" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default TelegramConnectionPanel;
