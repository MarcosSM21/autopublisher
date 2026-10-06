import { useCallback, useEffect, useState } from "react";
import {
  createAccount,
  listAccounts,
  updateAccount,
  updateProject,
  type AccountInput,
  type AccountUpdate,
  type ProjectInput,
} from "../api.ts";
import type { Account, Project } from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";
import AccountForm from "./AccountForm.tsx";
import AccountList from "./AccountList.tsx";
import ContentLibrary from "./ContentLibrary.tsx";
import ProjectForm from "./ProjectForm.tsx";
import PublicationQueue from "./PublicationQueue.tsx";

interface ProjectDetailProps {
  project: Project;
  onProjectChanged: () => Promise<void>;
}

function ProjectDetail({ project, onProjectChanged }: ProjectDetailProps) {
  const [editing, setEditing] = useState(false);
  const [view, setView] = useState<"accounts" | "content" | "queue">(
    "accounts",
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [accountsError, setAccountsError] = useState<string | null>(null);

  const loadAccounts = useCallback(
    () =>
      listAccounts(project.id)
        .then((loadedAccounts) => {
          setAccounts(loadedAccounts);
          setAccountsError(null);
        })
        .catch((caught: unknown) =>
          setAccountsError(toApiError(caught).message),
        )
        .finally(() => setAccountsLoaded(true)),
    [project.id],
  );

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  async function handleSave(values: ProjectInput) {
    await updateProject(project.id, values);
    setEditing(false);
    await onProjectChanged();
  }

  async function handleToggleActive() {
    setActionError(null);
    try {
      await updateProject(project.id, { is_active: !project.is_active });
      await onProjectChanged();
    } catch (caught) {
      setActionError(toApiError(caught).message);
    }
  }

  async function handleUpdateAccount(id: number, changes: AccountUpdate) {
    await updateAccount(id, changes);
    await loadAccounts();
  }

  async function handleCreateAccount(values: AccountInput) {
    await createAccount(project.id, values);
    await loadAccounts();
  }

  return (
    <section aria-label={project.name}>
      <h2>{project.name}</h2>
      <p>
        <span className="badge">
          {project.is_active ? "Active" : "Inactive"}
        </span>
      </p>
      {editing ? (
        <ProjectForm
          label="Edit project"
          initialValues={{
            name: project.name,
            description: project.description,
          }}
          submitLabel="Save"
          onSubmit={handleSave}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <p>
            {project.description ?? (
              <span className="muted">No description</span>
            )}
          </p>
          <p className="muted">
            Created {formatDate(project.created_at)} · Last updated{" "}
            {formatDate(project.updated_at)}
          </p>
          <div className="actions">
            <button type="button" onClick={() => setEditing(true)}>
              Edit project
            </button>
            <button type="button" onClick={handleToggleActive}>
              {project.is_active ? "Deactivate project" : "Activate project"}
            </button>
          </div>
          {actionError && (
            <p className="error" role="alert">
              {actionError}
            </p>
          )}
        </>
      )}

      <div className="actions view-switch">
        <button
          type="button"
          aria-pressed={view === "accounts"}
          onClick={() => setView("accounts")}
        >
          Accounts
        </button>
        <button
          type="button"
          aria-pressed={view === "content"}
          onClick={() => setView("content")}
        >
          Content
        </button>
        <button
          type="button"
          aria-pressed={view === "queue"}
          onClick={() => setView("queue")}
        >
          Queue
        </button>
      </div>

      {view === "queue" && <PublicationQueue project={project} />}
      {view === "content" && (
        <ContentLibrary
          project={project}
          onOpenQueue={() => setView("queue")}
        />
      )}
      {view === "accounts" && (
        <>
          <h3>Accounts</h3>
          {accountsError && (
            <p className="error" role="alert">
              {accountsError}
            </p>
          )}
          {accountsLoaded && !accountsError && (
            <AccountList
              accounts={accounts}
              projectActive={project.is_active}
              onUpdate={handleUpdateAccount}
            />
          )}
          {project.is_active ? (
            <>
              <h3>Add account</h3>
              <AccountForm
                label="Add account"
                mode="create"
                submitLabel="Add account"
                onSubmit={handleCreateAccount}
                resetOnSuccess
              />
            </>
          ) : (
            <p className="muted">Reactivate this project to add accounts.</p>
          )}
        </>
      )}
    </section>
  );
}

export default ProjectDetail;
