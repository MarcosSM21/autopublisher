import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import {
  createPublications,
  listAccounts,
  listPublications,
  type ApiError,
} from "../api.ts";
import {
  type Account,
  type Content,
  type Project,
  type Publication,
} from "../types.ts";
import { accountName, fromDateTimeLocalValue, toApiError } from "../utils.ts";
import { FieldMessage } from "./ProjectForm.tsx";

interface PublicationCreateProps {
  project: Project;
  content: Content;
  onOpenQueue: () => void;
}

function PublicationCreate({
  project,
  content,
  onOpenQueue,
}: PublicationCreateProps) {
  const id = useId();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [publishAt, setPublishAt] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<Publication[] | null>(null);

  const load = useCallback(
    () =>
      Promise.all([listAccounts(project.id), listPublications(project.id)])
        .then(([loadedAccounts, loadedPublications]) => {
          setAccounts(loadedAccounts);
          setPublications(loadedPublications);
          setLoadError(null);
        })
        .catch((caught: unknown) => setLoadError(toApiError(caught).message)),
    [project.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) {
    return (
      <p className="error" role="alert">
        {loadError}
      </p>
    );
  }
  if (!project.is_active) {
    return (
      <p className="muted">Reactivate the project to prepare publications.</p>
    );
  }
  if (!content.file_available) {
    return (
      <p className="muted">The media file of this content is not available.</p>
    );
  }
  if (accounts === null) {
    return null;
  }
  const activeAccounts = accounts.filter((account) => account.is_active);
  if (activeAccounts.length === 0) {
    return (
      <p className="muted">Add an active account to this project first.</p>
    );
  }

  // Accounts that already have an active publication of this content.
  const taken = new Set(
    publications
      .filter(
        (publication) =>
          publication.content_id === content.id &&
          publication.status !== "cancelled",
      )
      .map((publication) => publication.account_id),
  );

  function toggle(accountId: number) {
    setSelected((current) =>
      current.includes(accountId)
        ? current.filter((value) => value !== accountId)
        : [...current, accountId],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setCreated(null);
    try {
      const result = await createPublications(content.id, {
        account_ids: selected,
        ...(publishAt
          ? { scheduled_at: fromDateTimeLocalValue(publishAt) }
          : {}),
      });
      setCreated(result);
      setSelected([]);
      setPublishAt("");
      await load();
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  const accountMessages =
    error?.fields
      .filter((field) => field.field === "account_ids")
      .map((field) => field.message) ?? [];

  return (
    <form aria-label="Prepare publications" onSubmit={handleSubmit} noValidate>
      <fieldset>
        <legend>Target accounts</legend>
        {activeAccounts.map((account) => {
          const isTaken = taken.has(account.id);
          return (
            <label key={account.id} className="checkbox">
              <span>
                <input
                  type="checkbox"
                  checked={!isTaken && selected.includes(account.id)}
                  disabled={isTaken || saving}
                  onChange={() => toggle(account.id)}
                />{" "}
                {accountName(account)}
                {account.display_name && ` · ${account.display_name}`}
              </span>
              {isTaken && (
                <span className="muted">Already has an active publication</span>
              )}
            </label>
          );
        })}
      </fieldset>
      <label htmlFor={`${id}-publish-at`}>Publish at (optional)</label>
      <input
        id={`${id}-publish-at`}
        type="datetime-local"
        value={publishAt}
        onChange={(event) => setPublishAt(event.target.value)}
        aria-invalid={error?.fieldMessage("scheduled_at") ? true : undefined}
      />
      <FieldMessage error={error} field="scheduled_at" />
      {error && !error.fieldMessage("scheduled_at") && (
        <div className="error" role="alert">
          <p>{error.message}</p>
          {accountMessages.length > 0 && (
            <ul>
              {accountMessages.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="actions">
        <button type="submit" disabled={saving || selected.length === 0}>
          Create publications
        </button>
      </div>
      {created && (
        <div role="status">
          <p>
            Created {created.length}{" "}
            {created.length === 1 ? "publication" : "publications"} for{" "}
            {created
              .map((publication) => accountName(publication.account))
              .join(", ")}
            .
          </p>
          <button type="button" onClick={onOpenQueue}>
            Open queue
          </button>
        </div>
      )}
    </form>
  );
}

export default PublicationCreate;
