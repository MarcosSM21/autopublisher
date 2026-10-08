import { useState } from "react";
import type { AccountInput, AccountUpdate } from "../api.ts";
import { platformLabel, type Account } from "../types.ts";
import { toApiError } from "../utils.ts";
import AccountForm from "./AccountForm.tsx";
import InstagramConnectionPanel from "./InstagramConnectionPanel.tsx";
import YouTubeConnectionPanel from "./YouTubeConnectionPanel.tsx";

interface AccountListProps {
  accounts: Account[];
  projectActive: boolean;
  onUpdate: (id: number, changes: AccountUpdate) => Promise<void>;
}

function AccountList({ accounts, projectActive, onUpdate }: AccountListProps) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [toggleError, setToggleError] = useState<{
    id: number;
    message: string;
  } | null>(null);

  async function handleSave(id: number, values: AccountInput) {
    await onUpdate(id, {
      handle: values.handle,
      display_name: values.display_name,
    });
    setEditingId(null);
  }

  async function handleToggle(account: Account) {
    setToggleError(null);
    try {
      await onUpdate(account.id, { is_active: !account.is_active });
    } catch (caught) {
      setToggleError({ id: account.id, message: toApiError(caught).message });
    }
  }

  return (
    <>
      {accounts.length === 0 && <p className="muted">No accounts yet.</p>}
      <ul className="plain" aria-label="Accounts">
        {accounts.map((account) => (
          <li key={account.id} className="account">
            {editingId === account.id ? (
              <AccountForm
                label="Edit account"
                mode="edit"
                initialValues={account}
                submitLabel="Save"
                onSubmit={(values) => handleSave(account.id, values)}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <>
                <strong>{platformLabel(account.platform)}</strong>{" "}
                <span className={account.is_active ? undefined : "inactive"}>
                  @{account.handle}
                </span>{" "}
                {account.display_name && (
                  <span className="muted">{account.display_name}</span>
                )}
                <span className="badge">
                  {account.is_active ? "Active" : "Inactive"}
                </span>
                <div className="actions">
                  <button
                    type="button"
                    onClick={() => setEditingId(account.id)}
                  >
                    Edit
                  </button>
                  <button type="button" onClick={() => handleToggle(account)}>
                    {account.is_active ? "Deactivate" : "Activate"}
                  </button>
                </div>
                {toggleError?.id === account.id && (
                  <p className="error" role="alert">
                    {toggleError.message}
                  </p>
                )}
                {account.platform === "youtube" && (
                  <YouTubeConnectionPanel
                    account={account}
                    projectActive={projectActive}
                  />
                )}
                {account.platform === "instagram" && (
                  <InstagramConnectionPanel
                    account={account}
                    projectActive={projectActive}
                  />
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export default AccountList;
