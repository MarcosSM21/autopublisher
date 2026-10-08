import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  authorizeInstagram,
  cancelInstagramAttempt,
  completeInstagramAttempt,
  confirmInstagramAttempt,
  disconnectInstagram,
  getInstagramConnection,
  verifyInstagramConnection,
} from "../api.ts";
import {
  INSTAGRAM_ACCOUNT_TYPE_LABELS,
  INSTAGRAM_CONNECTION_STATUS_LABELS,
  platformLabel,
  type Account,
  type InstagramConnection,
  type InstagramIdentity,
  type InstagramOAuthAttempt,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

/** Errors about the pasted address itself: the attempt is still waiting for it. */
const RETRY_PASTE_CODES = [
  "instagram_oauth_redirect_url_invalid",
  "instagram_oauth_state_invalid",
  "validation_error",
];
/** Verify errors after which the backend marked the connection to reconnect. */
const RECONNECT_CODES = [
  "instagram_reconnect_required",
  "instagram_identity_mismatch",
  "instagram_account_not_professional",
];

interface InstagramConnectionPanelProps {
  account: Account;
  projectActive: boolean;
}

function IdentitySummary({ identity }: { identity: InstagramIdentity }) {
  const [pictureFailed, setPictureFailed] = useState(false);
  const picture = identity.profile_picture_url;
  return (
    <span className="channel">
      {picture && !pictureFailed ? (
        <img
          src={picture}
          alt={`@${identity.username}`}
          width={24}
          onError={() => setPictureFailed(true)}
        />
      ) : (
        <span className="avatar-placeholder" aria-hidden="true" />
      )}
      <strong>@{identity.username}</strong>
      <span className="muted">
        {INSTAGRAM_ACCOUNT_TYPE_LABELS[identity.account_type]}
      </span>
      <span className="muted">
        Instagram account ID: {identity.instagram_user_id}
      </span>
    </span>
  );
}

function InstagramConnectionPanel({
  account,
  projectActive,
}: InstagramConnectionPanelProps) {
  const [connection, setConnection] = useState<InstagramConnection | null>(
    null,
  );
  // Only the public attempt id is kept; the pasted address is discarded on send.
  const [pendingAttemptId, setPendingAttemptId] = useState<string | null>(null);
  const [redirectUrl, setRedirectUrl] = useState("");
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [awaiting, setAwaiting] = useState<InstagramOAuthAttempt | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(
    () =>
      getInstagramConnection(account.id)
        .then(setConnection)
        .catch((caught: unknown) => setError(toApiError(caught).message)),
    [account.id],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function closePaste() {
    setPendingAttemptId(null);
    setRedirectUrl("");
    setFallbackUrl(null);
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
      const result = await authorizeInstagram(account.id);
      if (tab) {
        tab.location.href = result.authorization_url;
        setFallbackUrl(null);
      } else {
        setFallbackUrl(result.authorization_url);
      }
      setRedirectUrl("");
      setPendingAttemptId(result.attempt_id);
    } catch (caught) {
      tab?.close();
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (apiError.code === "instagram_oauth_not_configured") {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  function handleResult(attempt: InstagramOAuthAttempt) {
    if (attempt.status === "awaiting_confirmation") {
      setAwaiting(attempt);
      return;
    }
    setAwaiting(null);
    if (attempt.status === "completed") {
      setNotice("Instagram account connected.");
      if (attempt.connection) {
        setConnection(attempt.connection);
      } else {
        void reload();
      }
    } else if (attempt.status === "failed") {
      setError(attempt.error?.message ?? "The connection failed.");
      void reload();
    }
  }

  async function completeConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingAttemptId === null) {
      return;
    }
    // The pasted address carries the authorization code and state: it leaves the
    // form as soon as it is sent and is never kept anywhere.
    const pasted = redirectUrl.trim();
    setRedirectUrl("");
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const attempt = await completeInstagramAttempt(pendingAttemptId, pasted);
      closePaste();
      handleResult(attempt);
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (!RETRY_PASTE_CODES.includes(apiError.code)) {
        closePaste();
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancelPaste() {
    const attemptId = pendingAttemptId;
    closePaste();
    setError(null);
    if (attemptId === null) {
      return;
    }
    try {
      await cancelInstagramAttempt(attemptId);
    } catch {
      // The attempt expires on its own; nothing else depends on it.
    }
  }

  async function confirmChange(attempt: InstagramOAuthAttempt) {
    setError(null);
    setBusy(true);
    try {
      handleResult(await confirmInstagramAttempt(attempt.attempt_id));
    } catch (caught) {
      setAwaiting(null);
      setError(toApiError(caught).message);
      void reload();
    } finally {
      setBusy(false);
    }
  }

  async function keepCurrent(attempt: InstagramOAuthAttempt) {
    setError(null);
    setBusy(true);
    try {
      await cancelInstagramAttempt(attempt.attempt_id);
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
      setConnection(await verifyInstagramConnection(account.id));
      setNotice("Connection verified.");
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (RECONNECT_CODES.includes(apiError.code)) {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (
      !window.confirm(
        "Disconnect this Instagram account? AutoPublisher will delete its stored credentials.",
      )
    ) {
      return;
    }
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      setConnection(await disconnectInstagram(account.id));
      closePaste();
      setAwaiting(null);
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
      <p className="muted">Loading Instagram connection…</p>
    );
  }

  const connectable = account.is_active && projectActive;
  const configured = connection.oauth_configured;
  const canStart =
    connectable &&
    configured &&
    !busy &&
    pendingAttemptId === null &&
    awaiting === null;
  const { status, identity } = connection;

  return (
    <div
      className="instagram-connection"
      role="group"
      aria-label={`Instagram connection of @${account.handle}`}
    >
      <span className={`badge connection-${status}`}>
        {INSTAGRAM_CONNECTION_STATUS_LABELS[status]}
      </span>
      {identity && (
        <IdentitySummary
          key={identity.profile_picture_url ?? ""}
          identity={identity}
        />
      )}
      {connection.access_expires_at && (
        <span className="muted">
          Access expires {formatDate(connection.access_expires_at)}
        </span>
      )}

      {status === "reconnect_required" && (
        <p role="note">
          AutoPublisher can no longer use this Instagram connection: the access
          expired, was withdrawn or no longer matches. Reconnect the account to
          renew it.
        </p>
      )}

      <div className="actions">
        {status === "not_connected" && configured && (
          <button
            type="button"
            disabled={!canStart}
            onClick={startAuthorization}
          >
            Connect Instagram
          </button>
        )}
        {status === "connected" && (
          <button
            type="button"
            disabled={busy || !connectable}
            onClick={verify}
          >
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
          Reactivate the account (or project) to connect, reconnect or verify
          it.
        </p>
      )}
      {connectable && !configured && (
        <p className="muted" role="note">
          Instagram is not configured. Create a Meta App with Instagram Login
          and save its settings as <code>backend/data/instagram-app.json</code>.
          See docs/instagram-accounts.md.
        </p>
      )}

      {pendingAttemptId !== null && (
        <form
          className="instagram-paste"
          aria-label="Complete Instagram connection"
          onSubmit={completeConnection}
        >
          <p className="muted">
            Allow access in the Instagram tab. Instagram then opens a page that
            cannot be displayed: copy the full address from that tab&apos;s
            address bar and paste it here.{" "}
            {fallbackUrl && (
              <a href={fallbackUrl} target="_blank" rel="noreferrer">
                Open Instagram authorization
              </a>
            )}
          </p>
          <label>
            Paste the address of the page Instagram opened
            <input
              type="text"
              value={redirectUrl}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setRedirectUrl(event.target.value)}
            />
          </label>
          <div className="actions">
            <button type="submit" disabled={busy || redirectUrl.trim() === ""}>
              Complete connection
            </button>
            <button type="button" disabled={busy} onClick={cancelPaste}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {awaiting && (
        <div
          className="channel-change"
          role="region"
          aria-label="Confirm Instagram account change"
        >
          <p>
            <strong>
              {platformLabel(account.platform)} @{account.handle}
            </strong>
            {account.display_name && ` (${account.display_name})`} is already
            linked to another Instagram account. Replace it?
          </p>
          <dl>
            <dt>Current Instagram account</dt>
            <dd>
              {awaiting.current_identity ? (
                <IdentitySummary identity={awaiting.current_identity} />
              ) : (
                "None"
              )}
            </dd>
            <dt>New Instagram account</dt>
            <dd>
              {awaiting.new_identity && (
                <IdentitySummary identity={awaiting.new_identity} />
              )}
            </dd>
          </dl>
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => confirmChange(awaiting)}
            >
              Replace with the new account
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => keepCurrent(awaiting)}
            >
              Keep current account
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
          AutoPublisher deleted its stored credentials. To also remove
          AutoPublisher&apos;s access in Instagram, open Instagram → Settings
          and activity → Website permissions → Apps and websites and remove the
          app.
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

export default InstagramConnectionPanel;
