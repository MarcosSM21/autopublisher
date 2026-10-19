import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { discardAccount, updateAccount } from "../../api.ts";
import ConnectionPanel from "../../components/ConnectionPanel.tsx";
import type { Account, AccountHealth, Project } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import DetailSurface from "../../ui/DetailSurface.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
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
}

/**
 * Status, identity and problem first; the name, (de)activation and discard
 * next; the existing connection panel inside "Connection & technical details",
 * opened when the account needs Connect, Reconnect or Finish setup.
 */
function AccountDetail({
  project,
  health,
  account,
  onChanged,
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
            <DiscardSetup
              accountId={account.id}
              parentPath={base}
              onDiscarded={onChanged}
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

/** Removes an abandoned setup (provisional account) after confirmation. */
export function DiscardSetup({
  accountId,
  parentPath,
  onDiscarded,
}: {
  accountId: number;
  parentPath: string;
  onDiscarded: () => void;
}) {
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function discard() {
    setBusy(true);
    setError(null);
    try {
      await discardAccount(accountId);
      setConfirming(false);
      onDiscarded();
      void navigate(parentPath);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="ghost" onClick={() => setConfirming(true)}>
        Discard setup
      </Button>
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Discard this setup?"
        description="The account was never connected. Discarding removes it from this project."
        footer={
          <>
            <Button onClick={() => setConfirming(false)}>Keep it</Button>
            <Button
              variant="danger"
              loading={busy}
              onClick={() => void discard()}
            >
              Discard setup
            </Button>
          </>
        }
      >
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </Dialog>
    </>
  );
}

export default AccountDetail;
