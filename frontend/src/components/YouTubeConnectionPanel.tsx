import { useCallback, useEffect, useRef, useState } from "react";
import {
  authorizeYouTube,
  cancelOAuthAttempt,
  confirmOAuthAttempt,
  disconnectYouTube,
  getOAuthAttempt,
  getYouTubeConnection,
  verifyYouTubeConnection,
} from "../api.ts";
import {
  platformLabel,
  YOUTUBE_CONNECTION_STATUS_LABELS,
  type Account,
  type OAuthAttempt,
  type YouTubeChannel,
  type YouTubeConnection,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

export const POLL_INTERVAL_MS = 2000;
const GOOGLE_CONNECTIONS_URL = "https://myaccount.google.com/connections";
const EXPIRED_MESSAGE = "The authorization expired. Try again.";

interface YouTubeConnectionPanelProps {
  account: Account;
  projectActive: boolean;
}

function ChannelSummary({ channel }: { channel: YouTubeChannel }) {
  return (
    <span className="channel">
      {channel.thumbnail_url && (
        <img src={channel.thumbnail_url} alt={channel.title} width={24} />
      )}
      <strong>{channel.title}</strong>
      {channel.handle && <span className="muted">{channel.handle}</span>}
      <span className="muted">Channel ID: {channel.id}</span>
    </span>
  );
}

function YouTubeConnectionPanel({
  account,
  projectActive,
}: YouTubeConnectionPanelProps) {
  const [connection, setConnection] = useState<YouTubeConnection | null>(null);
  const [awaiting, setAwaiting] = useState<OAuthAttempt | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef<number | null>(null);

  const reload = useCallback(
    () =>
      getYouTubeConnection(account.id)
        .then(setConnection)
        .catch((caught: unknown) => setError(toApiError(caught).message)),
    [account.id],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  function finishWaiting() {
    stopPolling();
    setWaiting(false);
    setFallbackUrl(null);
  }

  function handleAttempt(attempt: OAuthAttempt) {
    switch (attempt.status) {
      case "pending":
        schedulePoll(attempt.attempt_id);
        return;
      case "awaiting_confirmation":
        finishWaiting();
        setAwaiting(attempt);
        return;
      case "completed":
        finishWaiting();
        setAwaiting(null);
        setNotice("YouTube channel connected.");
        void reload();
        return;
      case "failed":
        finishWaiting();
        setAwaiting(null);
        setError(attempt.error?.message ?? "The connection failed.");
        void reload();
        return;
      case "expired":
        finishWaiting();
        setAwaiting(null);
        setError(EXPIRED_MESSAGE);
        return;
      case "cancelled":
        finishWaiting();
        setAwaiting(null);
        return;
    }
  }

  function schedulePoll(attemptId: string) {
    stopPolling();
    pollTimer.current = window.setTimeout(async () => {
      pollTimer.current = null;
      try {
        handleAttempt(await getOAuthAttempt(attemptId));
      } catch (caught) {
        finishWaiting();
        const apiError = toApiError(caught);
        // Purged after its retention period, or the backend restarted.
        setError(
          apiError.code === "oauth_attempt_not_found"
            ? EXPIRED_MESSAGE
            : apiError.message,
        );
        void reload();
      }
    }, POLL_INTERVAL_MS);
  }

  /** Connect and Reconnect share this handler, and therefore its protections. */
  async function startAuthorization() {
    setError(null);
    setNotice(null);
    setDisconnected(false);
    if (!connection?.oauth_configured) {
      return; // The setup instructions are shown instead; never open a tab.
    }
    // Opened synchronously in the click so pop-up blockers allow it.
    const tab = window.open("", "_blank");
    setBusy(true);
    try {
      const result = await authorizeYouTube(account.id);
      if (tab) {
        tab.location.href = result.authorization_url;
      } else {
        setFallbackUrl(result.authorization_url);
      }
      setWaiting(true);
      schedulePoll(result.attempt_id);
    } catch (caught) {
      tab?.close();
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (apiError.code === "oauth_not_configured") {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmChange(attempt: OAuthAttempt) {
    setError(null);
    setBusy(true);
    try {
      handleAttempt(await confirmOAuthAttempt(attempt.attempt_id));
    } catch (caught) {
      setAwaiting(null);
      setError(toApiError(caught).message);
      void reload();
    } finally {
      setBusy(false);
    }
  }

  async function keepCurrent(attempt: OAuthAttempt) {
    setError(null);
    setBusy(true);
    try {
      await cancelOAuthAttempt(attempt.attempt_id);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setAwaiting(null);
      setBusy(false);
    }
  }

  async function verify() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      setConnection(await verifyYouTubeConnection(account.id));
      setNotice("Connection verified.");
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (apiError.code === "reconnect_required") {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Disconnect this YouTube channel? AutoPublisher will delete its stored credentials.",
      )
    ) {
      return;
    }
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      setConnection(await disconnectYouTube(account.id));
      setDisconnected(true);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setBusy(false);
    }
  }

  if (connection === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading YouTube connection…</p>
    );
  }

  const connectable = account.is_active && projectActive;
  const canStart = connectable && !busy && !waiting && awaiting === null;
  const { status, channel } = connection;

  return (
    <div
      className="youtube-connection"
      role="group"
      aria-label={`YouTube connection of @${account.handle}`}
    >
      <span className={`badge connection-${status}`}>
        {YOUTUBE_CONNECTION_STATUS_LABELS[status]}
      </span>
      {channel && <ChannelSummary channel={channel} />}
      {connection.connected_at && (
        <span className="muted">
          Connected {formatDate(connection.connected_at)}
        </span>
      )}

      <div className="actions">
        {status === "not_connected" && (
          <button
            type="button"
            disabled={!canStart}
            onClick={startAuthorization}
          >
            Connect
          </button>
        )}
        {status === "connected" && (
          <button type="button" disabled={busy} onClick={verify}>
            Verify connection
          </button>
        )}
        {status !== "not_connected" && (
          <button
            type="button"
            disabled={!canStart}
            onClick={startAuthorization}
          >
            Reconnect
          </button>
        )}
        {status !== "not_connected" && (
          <button type="button" disabled={busy} onClick={disconnect}>
            Disconnect
          </button>
        )}
      </div>

      {!connectable && (
        <p className="muted">
          Reactivate the account (or project) to connect it.
        </p>
      )}
      {connectable && !connection.oauth_configured && (
        <p className="muted" role="note">
          YouTube OAuth is not configured. Create a Desktop app OAuth client in
          Google Cloud and save its JSON as{" "}
          <code>backend/data/google-oauth-client.json</code>. See “Connecting
          YouTube” in the README.
        </p>
      )}
      {waiting && (
        <p className="muted" role="status">
          Waiting for the authorization in Google…{" "}
          {fallbackUrl && (
            <a href={fallbackUrl} target="_blank" rel="noreferrer">
              Open Google authorization
            </a>
          )}
        </p>
      )}

      {awaiting && (
        <div
          className="channel-change"
          role="region"
          aria-label="Confirm channel change"
        >
          <p>
            <strong>
              {platformLabel(account.platform)} @{account.handle}
            </strong>
            {account.display_name && ` (${account.display_name})`} is already
            linked to another channel. Replace it?
          </p>
          <dl>
            <dt>Current channel</dt>
            <dd>
              {awaiting.current_channel ? (
                <ChannelSummary channel={awaiting.current_channel} />
              ) : (
                "None"
              )}
            </dd>
            <dt>New channel</dt>
            <dd>
              {awaiting.new_channel && (
                <ChannelSummary channel={awaiting.new_channel} />
              )}
            </dd>
          </dl>
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => confirmChange(awaiting)}
            >
              Replace with this channel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => keepCurrent(awaiting)}
            >
              Keep current channel
            </button>
          </div>
        </div>
      )}

      {notice && (
        <p className="muted" role="status">
          {notice}
        </p>
      )}
      {disconnected && (
        <p className="muted" role="status">
          AutoPublisher deleted its stored credentials. To fully remove
          AutoPublisher&apos;s access to your Google account, go to{" "}
          <a href={GOOGLE_CONNECTIONS_URL} target="_blank" rel="noreferrer">
            myaccount.google.com/connections
          </a>
          . This affects every AutoPublisher connection that uses that Google
          account.
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

export default YouTubeConnectionPanel;
