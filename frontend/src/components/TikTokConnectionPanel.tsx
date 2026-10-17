import { useConnectionSignal } from "./useConnectionSignal.ts";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  authorizeTikTok,
  cancelTikTokAttempt,
  confirmTikTokAttempt,
  disconnectTikTok,
  getTikTokAttempt,
  getTikTokConnection,
  removeTikTokLocally,
  verifyTikTokConnection,
} from "../api.ts";
import {
  TIKTOK_CONNECTION_STATUS_LABELS,
  type Account,
  type TikTokAttemptIdentity,
  type TikTokConnection,
  type TikTokIdentity,
  type TikTokOAuthAttempt,
  type TikTokPermissions,
  type TikTokRevocation,
} from "../types.ts";
import { accountReference, formatDate, toApiError } from "../utils.ts";

export const POLL_INTERVAL_MS = 2000;
const EXPIRED_MESSAGE = "The authorization expired. Try again.";
const CANCELLED_MESSAGE = "The connection was cancelled.";
const CHANGE_CANCELLED_MESSAGE =
  "The change was cancelled. The linked TikTok account is unchanged.";
const MANAGE_PERMISSIONS_HINT =
  "In the TikTok app, go to Settings and privacy > Security and permissions > Manage app permissions and remove AutoPublisher.";
const RECONNECT_REQUIRED_EXPLANATION =
  "TikTok no longer accepts the saved authorization (it expired, was revoked or lost a permission). Reconnect the account to keep using it.";
const REVOCATION_MESSAGES: Record<TikTokRevocation, string> = {
  revoked:
    "Disconnected. TikTok confirmed that AutoPublisher's access was revoked.",
  already_invalid:
    "Disconnected. TikTok reported that the authorization was no longer valid, so there was nothing left to revoke.",
  not_revoked: `Removed locally without revoking. TikTok may still have AutoPublisher authorized. ${MANAGE_PERMISSIONS_HINT}`,
  not_connected: "This TikTok account was already disconnected.",
};

interface TikTokConnectionPanelProps {
  account: Account;
  projectActive: boolean;
  /** Called when the connection changes (not on the first load). */
  onConnectionChange?: () => void;
}

/** An in-progress authorization; the URL only lives in component memory. */
interface Pending {
  attemptId: string;
  authorizationUrl: string;
}

/** A reconnection that authorized another TikTok account. */
interface AccountChange {
  attemptId: string;
  current: TikTokAttemptIdentity | null;
  next: TikTokAttemptIdentity;
}

/** Steps of the Disconnect flow shown under the actions. */
type DisconnectStep =
  "confirm" | "revoke_failed" | "credential_missing" | "confirm_local";

function IdentitySummary({
  identity,
  reference,
}: {
  identity: TikTokIdentity;
  /** How the account is named when TikTok gives no display name. */
  reference: string;
}) {
  const [avatarFailed, setAvatarFailed] = useState(false);
  const name = identity.display_name ?? reference;
  return (
    <span className="channel">
      {identity.avatar_url && !avatarFailed ? (
        <img
          src={identity.avatar_url}
          alt={name}
          width={24}
          onError={() => setAvatarFailed(true)}
        />
      ) : (
        <span
          className="avatar-placeholder"
          aria-hidden="true"
          data-testid="tiktok-avatar-placeholder"
        />
      )}
      {identity.display_name && <strong>{identity.display_name}</strong>}
      <span className="muted">{reference}</span>
    </span>
  );
}

function describeIdentity(identity: TikTokAttemptIdentity | null): string {
  if (identity === null) {
    return "the linked TikTok account";
  }
  const name = identity.display_name ?? "a TikTok account";
  return `${name} (ID ending in ${identity.open_id_suffix})`;
}

function PermissionsSummary({
  permissions,
}: {
  permissions: TikTokPermissions | null;
}) {
  if (permissions === null) {
    return (
      <span className="muted">
        Permissions: unknown (the stored authorization cannot be read).
      </span>
    );
  }
  const origin =
    permissions.source === "token_refresh"
      ? "TikTok's last renewal"
      : "TikTok's last authorization";
  return (
    <span className="muted">
      Permissions {permissions.granted.join(", ") || "none"} granted according
      to {origin} ({formatDate(permissions.confirmed_at)}).
    </span>
  );
}

function InboxUploadCapability({
  permissions,
}: {
  permissions: TikTokPermissions;
}) {
  return (
    <span className="muted">
      {permissions.capabilities.inbox_upload
        ? "Upload to Inbox: available."
        : "Upload to Inbox: needs Reconnect (video.upload). Direct Post keeps working."}
    </span>
  );
}

function TikTokConnectionPanel({
  account,
  projectActive,
  onConnectionChange,
}: TikTokConnectionPanelProps) {
  const [connection, setConnection] = useState<TikTokConnection | null>(null);
  useConnectionSignal(connection?.status ?? null, onConnectionChange);
  const [pending, setPending] = useState<Pending | null>(null);
  const [change, setChange] = useState<AccountChange | null>(null);
  const [disconnectStep, setDisconnectStep] = useState<DisconnectStep | null>(
    null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef<number | null>(null);

  const reload = useCallback(
    () =>
      getTikTokConnection(account.id)
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

  function resetMessages() {
    setError(null);
    setNotice(null);
  }

  function finishWaiting() {
    stopPolling();
    setPending(null);
  }

  function handleAttempt(attempt: TikTokOAuthAttempt) {
    switch (attempt.status) {
      case "pending":
      case "processing":
        schedulePoll(attempt.attempt_id);
        return;
      case "completed":
        finishWaiting();
        setNotice("TikTok account connected.");
        void reload();
        return;
      case "failed":
        finishWaiting();
        setError(attempt.error?.message ?? "The connection failed.");
        void reload();
        return;
      case "awaiting_confirmation":
        finishWaiting();
        if (attempt.new_identity) {
          setChange({
            attemptId: attempt.attempt_id,
            current: attempt.current_identity,
            next: attempt.new_identity,
          });
        }
        return;
      case "expired":
        finishWaiting();
        setError(EXPIRED_MESSAGE);
        return;
      case "cancelled":
        finishWaiting();
        setNotice(CANCELLED_MESSAGE);
        return;
    }
  }

  function schedulePoll(attemptId: string) {
    stopPolling();
    pollTimer.current = window.setTimeout(async () => {
      pollTimer.current = null;
      try {
        handleAttempt(await getTikTokAttempt(attemptId));
      } catch (caught) {
        finishWaiting();
        const apiError = toApiError(caught);
        // Purged after its retention period, or the backend restarted.
        setError(
          apiError.code === "tiktok_oauth_attempt_not_found"
            ? EXPIRED_MESSAGE
            : apiError.message,
        );
        void reload();
      }
    }, POLL_INTERVAL_MS);
  }

  async function startAuthorization() {
    resetMessages();
    setDisconnectStep(null);
    setChange(null);
    if (!connection?.oauth_configured) {
      return; // The setup instructions are shown instead; never open a tab.
    }
    // Opened synchronously in the click so pop-up blockers allow it.
    const tab = window.open("", "_blank");
    setBusy(true);
    try {
      const result = await authorizeTikTok(account.id);
      if (tab) {
        tab.location.href = result.authorization_url;
      }
      setPending({
        attemptId: result.attempt_id,
        authorizationUrl: result.authorization_url,
      });
      schedulePoll(result.attempt_id);
    } catch (caught) {
      tab?.close();
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (apiError.code === "tiktok_oauth_not_configured") {
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (pending === null) {
      return;
    }
    const { attemptId } = pending;
    finishWaiting();
    setError(null);
    setBusy(true);
    try {
      await cancelTikTokAttempt(attemptId);
      setNotice(CANCELLED_MESSAGE);
    } catch (caught) {
      setError(toApiError(caught).message);
      void reload();
    } finally {
      setBusy(false);
    }
  }

  async function replaceAccount() {
    if (change === null) {
      return;
    }
    resetMessages();
    setBusy(true);
    try {
      await confirmTikTokAttempt(change.attemptId);
      setNotice("TikTok account replaced.");
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setChange(null);
      setBusy(false);
      void reload();
    }
  }

  async function keepAccount() {
    if (change === null) {
      return;
    }
    resetMessages();
    setBusy(true);
    try {
      await cancelTikTokAttempt(change.attemptId);
      setNotice(CHANGE_CANCELLED_MESSAGE);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setChange(null);
      setBusy(false);
    }
  }

  async function verify() {
    resetMessages();
    setBusy(true);
    try {
      setConnection(await verifyTikTokConnection(account.id));
      setNotice(
        "Connection verified with TikTok. Permissions are shown as granted in TikTok's last authorization or renewal.",
      );
    } catch (caught) {
      setError(toApiError(caught).message);
      void reload();
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    resetMessages();
    setBusy(true);
    try {
      const result = await disconnectTikTok(account.id);
      setDisconnectStep(null);
      setConnection(result.connection);
      setNotice(REVOCATION_MESSAGES[result.revocation]);
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError.message);
      if (apiError.code === "tiktok_revoke_failed") {
        setDisconnectStep("revoke_failed");
      } else if (apiError.code === "tiktok_credential_missing") {
        setDisconnectStep("credential_missing");
      } else {
        setDisconnectStep(null);
        void reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function removeLocally() {
    resetMessages();
    setBusy(true);
    try {
      const result = await removeTikTokLocally(account.id);
      setConnection(result.connection);
      setNotice(REVOCATION_MESSAGES[result.revocation]);
    } catch (caught) {
      setError(toApiError(caught).message);
      void reload();
    } finally {
      setDisconnectStep(null);
      setBusy(false);
    }
  }

  if (connection === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading TikTok connection…</p>
    );
  }

  const connectable = account.is_active && projectActive;
  const idle = !busy && pending === null && change === null;
  const { status, identity } = connection;
  const linked = status !== "not_connected";

  return (
    <div
      className="tiktok-connection"
      role="group"
      aria-label={`TikTok connection of ${accountReference(account)}`}
    >
      <span className={`badge connection-${status}`}>
        {TIKTOK_CONNECTION_STATUS_LABELS[status]}
      </span>
      {identity && (
        <IdentitySummary
          identity={identity}
          reference={accountReference(account)}
        />
      )}
      {linked && (
        <>
          {connection.access_expires_at && (
            <span className="muted">
              Access expires {formatDate(connection.access_expires_at)}
            </span>
          )}
          {connection.refresh_expires_at && (
            <span className="muted">
              Renewable authorization expires{" "}
              {formatDate(connection.refresh_expires_at)}
            </span>
          )}
          {connection.last_verified_at && (
            <span className="muted">
              Last verified {formatDate(connection.last_verified_at)}
            </span>
          )}
          <PermissionsSummary permissions={connection.permissions} />
          {status === "connected" && connection.permissions !== null && (
            <InboxUploadCapability permissions={connection.permissions} />
          )}
        </>
      )}
      {status === "reconnect_required" && (
        <p className="muted" role="note">
          {RECONNECT_REQUIRED_EXPLANATION}
        </p>
      )}

      <div className="actions">
        {connectable &&
          status === "not_connected" &&
          connection.oauth_configured &&
          pending === null && (
            <button type="button" disabled={!idle} onClick={startAuthorization}>
              Connect TikTok
            </button>
          )}
        {connectable && status === "connected" && (
          <button type="button" disabled={!idle} onClick={verify}>
            Verify connection
          </button>
        )}
        {connectable && linked && connection.oauth_configured && (
          <button type="button" disabled={!idle} onClick={startAuthorization}>
            Reconnect
          </button>
        )}
        {linked && (
          <button
            type="button"
            disabled={!idle}
            onClick={() => {
              resetMessages();
              setDisconnectStep("confirm");
            }}
          >
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
      {connectable && !connection.oauth_configured && (
        <p className="muted" role="note">
          TikTok is not configured. Create a TikTok for Developers Sandbox app
          with Login Kit (Desktop) and save its client key and secret as{" "}
          <code>backend/data/tiktok-app.json</code>. See{" "}
          <code>docs/tiktok-accounts.md</code>.
        </p>
      )}
      {pending && (
        <div className="muted" role="status">
          Connecting… Authorize AutoPublisher in the TikTok tab.{" "}
          <a href={pending.authorizationUrl} target="_blank" rel="noreferrer">
            Reopen TikTok authorization
          </a>{" "}
          <button type="button" disabled={busy} onClick={cancel}>
            Cancel
          </button>
        </div>
      )}

      {change && (
        <div role="alertdialog" aria-label="Replace the TikTok account">
          <p>
            This account is linked to {describeIdentity(change.current)}, but
            TikTok authorized {describeIdentity(change.next)}. Replace the
            linked TikTok account?
          </p>
          <button type="button" disabled={busy} onClick={replaceAccount}>
            Replace
          </button>{" "}
          <button type="button" disabled={busy} onClick={keepAccount}>
            Cancel
          </button>
        </div>
      )}

      {disconnectStep === "confirm" && (
        <div role="alertdialog" aria-label="Disconnect TikTok">
          <p>
            Disconnect this TikTok account? AutoPublisher will revoke its access
            in TikTok. The account and its publications are kept.
          </p>
          <button type="button" disabled={busy} onClick={disconnect}>
            Confirm disconnect
          </button>{" "}
          <button
            type="button"
            disabled={busy}
            onClick={() => setDisconnectStep(null)}
          >
            Keep connection
          </button>
        </div>
      )}
      {(disconnectStep === "revoke_failed" ||
        disconnectStep === "credential_missing") && (
        <div className="actions">
          {disconnectStep === "revoke_failed" && (
            <button type="button" disabled={busy} onClick={disconnect}>
              Retry
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => setDisconnectStep("confirm_local")}
          >
            Remove locally without revoking
          </button>
        </div>
      )}
      {disconnectStep === "confirm_local" && (
        <div role="alertdialog" aria-label="Remove locally without revoking">
          <p>
            AutoPublisher will forget this connection without revoking it, so
            TikTok may still have AutoPublisher authorized.{" "}
            {MANAGE_PERMISSIONS_HINT}
          </p>
          <button type="button" disabled={busy} onClick={removeLocally}>
            Remove locally
          </button>{" "}
          <button
            type="button"
            disabled={busy}
            onClick={() => setDisconnectStep(null)}
          >
            Back
          </button>
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

export default TikTokConnectionPanel;
