import { useId, useState, type FormEvent } from "react";
import { createTextPublications, type ApiError } from "../api.ts";
import { type Account, type Project, type Publication } from "../types.ts";
import {
  accountName,
  fromDateTimeLocalValue,
  parseHashtags,
  textPostAccounts,
  toApiError,
} from "../utils.ts";
import { FieldMessage } from "./ProjectForm.tsx";
import { AutoPublishConsent } from "./PublicationCreate.tsx";

interface TextPublicationCreateProps {
  project: Project;
  accounts: Account[];
  onCreated: (created: Publication[]) => void;
  onCancel: () => void;
}

/** A post without media: the text and hashtags are the publication's own. */
function TextPublicationCreate({
  project,
  accounts,
  onCreated,
  onCancel,
}: TextPublicationCreateProps) {
  const id = useId();
  const candidates = textPostAccounts(accounts);
  const [text, setText] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [selected, setSelected] = useState<number[]>(
    candidates.length === 1 ? [candidates[0].id] : [],
  );
  const [publishAt, setPublishAt] = useState("");
  // Explicit consent; never enabled silently (Feature 007).
  const [autoPublish, setAutoPublish] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

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
    try {
      const created = await createTextPublications(project.id, {
        account_ids: selected,
        description: text,
        hashtags: parseHashtags(hashtags),
        ...(publishAt
          ? {
              scheduled_at: fromDateTimeLocalValue(publishAt),
              auto_publish_enabled: autoPublish,
            }
          : {}),
      });
      onCreated(created);
    } catch (caught) {
      setError(toApiError(caught));
      setSaving(false);
    }
  }

  const accountMessages =
    error?.fields
      .filter((field) => field.field === "account_ids")
      .map((field) => field.message) ?? [];
  const fieldErrors = ["description", "hashtags", "scheduled_at"];

  return (
    <form aria-label="New text post" onSubmit={handleSubmit} noValidate>
      <h4>New text post</h4>
      <label htmlFor={`${id}-text`}>Text</label>
      <textarea
        id={`${id}-text`}
        rows={4}
        value={text}
        disabled={saving}
        onChange={(event) => setText(event.target.value)}
        aria-invalid={error?.fieldMessage("description") ? true : undefined}
      />
      <FieldMessage error={error} field="description" />
      <label htmlFor={`${id}-hashtags`}>Hashtags (optional)</label>
      <input
        id={`${id}-hashtags`}
        value={hashtags}
        disabled={saving}
        onChange={(event) => setHashtags(event.target.value)}
        aria-invalid={error?.fieldMessage("hashtags") ? true : undefined}
      />
      <FieldMessage error={error} field="hashtags" />
      <fieldset>
        <legend>Target accounts</legend>
        {candidates.map((account) => (
          <label key={account.id} className="checkbox">
            <span>
              <input
                type="checkbox"
                checked={selected.includes(account.id)}
                disabled={saving}
                onChange={() => toggle(account.id)}
              />{" "}
              {accountName(account)}
              {account.display_name && ` · ${account.display_name}`}
            </span>
          </label>
        ))}
      </fieldset>
      <label htmlFor={`${id}-publish-at`}>Publish at (optional)</label>
      <input
        id={`${id}-publish-at`}
        type="datetime-local"
        value={publishAt}
        disabled={saving}
        onChange={(event) => setPublishAt(event.target.value)}
        aria-invalid={error?.fieldMessage("scheduled_at") ? true : undefined}
      />
      <FieldMessage error={error} field="scheduled_at" />
      {publishAt && (
        <AutoPublishConsent
          checked={autoPublish}
          disabled={saving}
          onChange={setAutoPublish}
        />
      )}
      {error && !fieldErrors.some((field) => error.fieldMessage(field)) && (
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
          {publishAt && autoPublish
            ? "Schedule & enable auto-publish"
            : "Create text post"}
        </button>
        <button type="button" disabled={saving} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default TextPublicationCreate;
