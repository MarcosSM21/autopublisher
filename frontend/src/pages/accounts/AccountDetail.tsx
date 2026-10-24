import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { deleteObject, getDeletionPreview, updateAccount } from "../../api.ts";
import ConnectionPanel from "../../components/ConnectionPanel.tsx";
import DeleteConfirmDialog from "../../components/DeleteConfirmDialog.tsx";
import type { FlashState } from "../../shell/Flash.tsx";
import type { Account, AccountHealth, Project } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import DetailSurface from "../../ui/DetailSurface.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { formatDate, toApiError } from "../../utils.ts";
import {
  accountTitle,
  capabilitiesText,
  primaryAction,
} from "./presentation.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

interface AccountDetailProps {
  project: Project;
  health: AccountHealth;
  account: Account;
  /** Reloads health, accounts and the project overview. */
  onChanged: () => void;
  /** Deleted (or already gone): the page reloads without it. */
  onDeleted: () => void;
}

/**
 * Status, identity and problem first; the name, (de)activation and discard
 * next; the existing connection panel inside "Connection & technical details",
 * opened when the account needs Connect, Reconnect or Finish setup; Delete
 * account last, apart (a provisional account offers Discard setup instead:
 * the same delete).
 */
function AccountDetail({
  project,
  health,
  account,
  onChanged,
  onDeleted,
}: AccountDetailProps) {
  const base = `/p/${project.id}/accounts`;
  const action = primaryAction(health);
  // Controlled, and its content stays mounted while closed: the panel keeps
  // polling an attempt in progress.
  const [technicalOpen, setTechnicalOpen] = useState(action !== null);
  const [error, setError] = useState<string | null>(null);

  async function toggleActive() {
    setError(null);
    try {
      await updateAccount(account.id, { is_active: !account.is_active });
      onChanged();
    } catch (caught) {
      setError(toApiError(caught).message);
    }
  }

  return (
    <DetailSurface title={accountTitle(health)} parentPath={base}>
      <div className="ap-account-detail">
        <div className="ap-account-detail__status">
          <StatusBadge account={health.state} />
          {health.issue && (
            <p>{problemText(health.issue.message, health.issue.code)}</p>
          )}
          {action && (
            <p className="ap-meta">
              {action === "Finish setup"
                ? "Finish the remaining step below."
                : `${action} below to publish with this account.`}
            </p>
          )}
        </div>

        {health.identity && (
          <dl className="ap-account-detail__facts">
            <dt>Connected as</dt>
            <dd>
              {health.identity.name}
              {health.identity.username && ` (@${health.identity.username})`}
            </dd>
          </dl>
        )}
        {health.capabilities.length > 0 && (
          <p className="ap-meta">
            Can publish: {capabilitiesText(health.capabilities)}
          </p>
        )}

        <NameForm account={account} onSaved={onChanged} />

        <div className="ap-account-detail__actions">
          <Button onClick={() => void toggleActive()}>
            {account.is_active ? "Deactivate account" : "Activate account"}
          </Button>
          {health.can_discard && (
            <DeleteAccount
              accountId={account.id}
              parentPath={base}
              onDeleted={onDeleted}
              discard
            />
          )}
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <details
          className="ap-technical"
          open={technicalOpen}
          onToggle={(event) => setTechnicalOpen(event.currentTarget.open)}
        >
          <summary>Connection &amp; technical details</summary>
          <div className="ap-technical__body">
            <ConnectionPanel
              account={account}
              projectActive={project.is_active}
              onConnectionChange={onChanged}
            />
            {health.expiring && health.expires_at && (
              <p className="ap-meta">
                Login valid until {formatDate(health.expires_at)}
              </p>
            )}
          </div>
        </details>

        {!health.can_discard && (
          <section
            className="ap-account-detail__danger"
            aria-label="Delete account"
          >
            <DeleteAccount
              accountId={account.id}
              parentPath={base}
              onDeleted={onDeleted}
            />
          </section>
        )}
      </div>
    </DetailSurface>
  );
}

/** "Name in AutoPublisher": the only account field the user edits. */
function NameForm({
  account,
  onSaved,
}: {
  account: Account;
  onSaved: () => void;
}) {
  const id = useId();
  const [name, setName] = useState(account.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unchanged = name.trim() === (account.display_name ?? "");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await updateAccount(account.id, { display_name: name.trim() || null });
      setSaved(true);
      onSaved();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="ap-account-detail__name"
      aria-label="Account name"
      onSubmit={handleSubmit}
    >
      <div className="ap-field">
        <label htmlFor={id}>Name in AutoPublisher</label>
        <input
          id={id}
          value={name}
          placeholder="Optional"
          onChange={(event) => {
            setName(event.target.value);
            setSaved(false);
          }}
        />
      </div>
      <Button type="submit" loading={saving} disabled={unchanged}>
        Save name
      </Button>
      <p className="ap-meta ap-account-detail__saved" role="status">
        {saved ? "Name saved." : ""}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

/**
 * Delete account, or Discard setup for an abandoned (provisional) one: the same
 * preview, one confirmation and DELETE with its token. The account on the
 * platform is never contacted.
 */
export function DeleteAccount({
  accountId,
  parentPath,
  onDeleted,
  discard = false,
}: {
  accountId: number;
  parentPath: string;
  onDeleted: () => void;
  discard?: boolean;
}) {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);

  function deleted() {
    setConfirming(false);
    onDeleted();
    const state: FlashState = { flash: "Account deleted." };
    void navigate(parentPath, { state });
  }

  return (
    <>
      <Button
        variant={discard ? "ghost" : "secondary"}
        className={discard ? undefined : "ap-delete-entry"}
        onClick={() => setConfirming(true)}
      >
        {discard ? "Discard setup" : "Delete account"}
      </Button>
      {confirming && (
        <DeleteConfirmDialog
          title={discard ? "Discard this setup?" : "Delete account?"}
          description={
            discard
              ? "The account was never connected. Discarding removes it from this project."
              : undefined
          }
          confirmLabel={discard ? "Discard setup" : "Delete"}
          loadPreview={() => getDeletionPreview("account", accountId)}
          remove={(confirmation) =>
            deleteObject("account", accountId, confirmation)
          }
          onDeleted={deleted}
          onClose={() => setConfirming(false)}
        />
      )}
    </>
  );
}

export default AccountDetail;
