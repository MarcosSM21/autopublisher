import { useEffect, useId, useState, type FormEvent } from "react";
import {
  cancelPublication,
  getPublication,
  getPublishCheck,
  reactivatePublication,
  updatePublication,
  type ApiError,
  type PublicationUpdate,
} from "../api.ts";
import {
  PUBLICATION_STATUS_LABELS,
  type Publication,
  type PublicationStatus,
  type PublishCheck,
} from "../types.ts";
import {
  accountName,
  formatDate,
  fromDateTimeLocalValue,
  isOverdue,
  parseHashtags,
  toApiError,
  toDateTimeLocalValue,
} from "../utils.ts";
import { MediaPreview } from "./ContentDetail.tsx";
import { FormError } from "./FormError.tsx";
import { FieldMessage } from "./ProjectForm.tsx";
import PublicationAttempts from "./PublicationAttempts.tsx";
import PublishNowDialog from "./PublishNowDialog.tsx";
import YouTubePublishOptions from "./YouTubePublishOptions.tsx";

/** How often a publication being published is reloaded. */
export const POLL_INTERVAL_MS = 2000;

/** Statuses from which "Publish now" can run (research.md §13). */
const PUBLISHABLE: PublicationStatus[] = ["unscheduled", "scheduled", "failed"];
/** Statuses whose date can still be changed. */
const SCHEDULABLE: PublicationStatus[] = ["unscheduled", "scheduled"];

interface PublicationDetailProps {
  publication: Publication;
  /** Reloads the queue; the notice, if any, is shown to the user. */
  onChanged: (notice?: string) => Promise<void>;
}

const DATE_REMOVED_NOTICE =
  "The scheduled date had passed and was removed. Choose a new date.";

/** Why a publication cannot be scheduled or reactivated, if it cannot. */
function preparationBlocker(publication: Publication): string | null {
  if (!publication.project_active) {
    return "Reactivate the project to schedule this publication.";
  }
  if (!publication.account.is_active) {
    return "Reactivate the account to schedule this publication.";
  }
  if (!publication.content.file_available) {
    return "The media file of this content is not available.";
  }
  return null;
}

function PublicationDetail({
  publication: initial,
  onChanged,
}: PublicationDetailProps) {
  // Kept locally so it can be refreshed while an upload runs.
  const [publication, setPublication] = useState(initial);
  const cancelled = publication.status === "cancelled";
  const blocker = preparationBlocker(publication);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  // Bumped after saving options so the publish check is loaded again.
  const [checkVersion, setCheckVersion] = useState(0);
  const isYouTube = publication.account.platform === "youtube";
  const publishable = isYouTube && PUBLISHABLE.includes(publication.status);
  const publishing = publication.status === "publishing";

  useEffect(() => {
    if (!publishing) {
      return;
    }
    const timer = window.setInterval(() => {
      getPublication(publication.id)
        .then((loaded) => {
          setPublication(loaded);
          if (loaded.status !== "publishing") {
            void onChanged();
          }
        })
        .catch(() => {
          // A failed poll is retried on the next tick.
        });
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [publishing, publication.id, onChanged]);

  function handlePublished(result: Publication) {
    setDialogOpen(false);
    setPublication(result);
    void onChanged();
  }

  async function run(action: () => Promise<Publication>) {
    setBusy(true);
    setActionError(null);
    try {
      const result = await action();
      const dateRemoved =
        publication.scheduled_at !== null && result.scheduled_at === null;
      await onChanged(
        cancelled && dateRemoved ? DATE_REMOVED_NOTICE : undefined,
      );
    } catch (caught) {
      setActionError(toApiError(caught).message);
      setBusy(false);
    }
  }

  return (
    <section aria-label="Publication details" className="publication-detail">
      <h3>
        {publication.content.title ?? publication.content.original_filename}
      </h3>
      <MediaPreview content={publication.content} />
      <p>
        {accountName(publication.account)}
        <span className={`badge status-${publication.status}`}>
          {PUBLICATION_STATUS_LABELS[publication.status]}
        </span>
        {isOverdue(publication) && (
          <span className="badge warning">Overdue</span>
        )}
      </p>

      {isYouTube && (
        <YouTubePublishOptions
          publication={publication}
          onSaved={() => setCheckVersion((version) => version + 1)}
        />
      )}
      {publishable && (
        <PublishAction
          publication={publication}
          checkVersion={checkVersion}
          dialogOpen={dialogOpen}
          onOpen={() => setDialogOpen(true)}
          onCancel={() => setDialogOpen(false)}
          onPublished={handlePublished}
        />
      )}
      <PublicationAttempts publication={publication} />

      {cancelled ? (
        <>
          <p>
            {publication.scheduled_at ? (
              <>Was scheduled for {formatDate(publication.scheduled_at)}</>
            ) : (
              <span className="muted">No date</span>
            )}
          </p>
          <MetadataSummary publication={publication} />
          <div className="actions">
            <button
              type="button"
              disabled={busy || blocker !== null}
              onClick={() => run(() => reactivatePublication(publication.id))}
            >
              Reactivate
            </button>
          </div>
          {blocker && <p className="muted">{blocker}</p>}
        </>
      ) : PUBLISHABLE.includes(publication.status) ? (
        <>
          {SCHEDULABLE.includes(publication.status) && (
            <ScheduleForm
              publication={publication}
              blocker={blocker}
              onChanged={onChanged}
            />
          )}
          <MetadataForm publication={publication} onChanged={onChanged} />
          <div className="actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => run(() => cancelPublication(publication.id))}
            >
              Cancel publication
            </button>
          </div>
        </>
      ) : (
        <>
          {publication.scheduled_at && (
            <p className="muted">
              Was scheduled for {formatDate(publication.scheduled_at)}
            </p>
          )}
          <MetadataSummary publication={publication} />
        </>
      )}
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}
    </section>
  );
}

function PublishAction({
  publication,
  checkVersion,
  dialogOpen,
  onOpen,
  onCancel,
  onPublished,
}: {
  publication: Publication;
  checkVersion: number;
  dialogOpen: boolean;
  onOpen: () => void;
  onCancel: () => void;
  onPublished: (publication: Publication) => void;
}) {
  const [check, setCheck] = useState<PublishCheck | null>(null);

  useEffect(() => {
    let active = true;
    getPublishCheck(publication.id)
      .then((loaded) => active && setCheck(loaded))
      .catch(() => active && setCheck(null));
    return () => {
      active = false;
    };
  }, [publication, checkVersion]);

  if (dialogOpen) {
    return (
      <PublishNowDialog
        publication={publication}
        onCancel={onCancel}
        onPublished={onPublished}
      />
    );
  }
  return (
    <div className="actions">
      <button
        type="button"
        disabled={check === null || !check.eligible}
        onClick={onOpen}
      >
        Publish now
      </button>
      {check && !check.eligible && (
        <ul className="muted" aria-label="Why this cannot be published">
          {check.problems.map((problem) => (
            <li key={`${problem.code}-${problem.field ?? ""}`}>
              {problem.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ScheduleForm({
  publication,
  blocker,
  onChanged,
}: {
  publication: Publication;
  blocker: string | null;
  onChanged: () => Promise<void>;
}) {
  const id = useId();
  const [value, setValue] = useState(
    publication.scheduled_at
      ? toDateTimeLocalValue(publication.scheduled_at)
      : "",
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(scheduledAt: string | null) {
    setSaving(true);
    setError(null);
    try {
      await updatePublication(publication.id, { scheduled_at: scheduledAt });
      await onChanged();
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void save(fromDateTimeLocalValue(value));
  }

  return (
    <form aria-label="Schedule" onSubmit={handleSubmit} noValidate>
      <label htmlFor={`${id}-publish-at`}>Publish at</label>
      <input
        id={`${id}-publish-at`}
        type="datetime-local"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-invalid={error?.fieldMessage("scheduled_at") ? true : undefined}
      />
      <FieldMessage error={error} field="scheduled_at" />
      <FormError error={error} fields={["scheduled_at"]} />
      <div className="actions">
        <button
          type="submit"
          disabled={saving || value === "" || blocker !== null}
        >
          Save date
        </button>
        {publication.scheduled_at && (
          <button type="button" disabled={saving} onClick={() => save(null)}>
            Remove date
          </button>
        )}
      </div>
      {blocker && <p className="muted">{blocker}</p>}
    </form>
  );
}

type MetadataField = "title" | "description" | "hashtags";

const FIELD_LABELS: Record<MetadataField, string> = {
  title: "Title",
  description: "Description",
  hashtags: "Hashtags",
};

const EMPTY_LABELS: Record<MetadataField, string> = {
  title: "No title",
  description: "No description",
  hashtags: "No hashtags",
};

function overrideOf(
  publication: Publication,
  field: MetadataField,
): string | string[] | null {
  return publication[`${field}_override`];
}

/** Text shown for a value: hashtags as "#a #b", empty values as null. */
function displayValue(value: string | string[] | null): string | null {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((tag) => `#${tag}`).join(" ") : null;
  }
  return value ? value : null;
}

function MetadataSummary({ publication }: { publication: Publication }) {
  return (
    <dl>
      {(Object.keys(FIELD_LABELS) as MetadataField[]).map((field) => (
        <div key={field}>
          <dt>
            {FIELD_LABELS[field]}{" "}
            <span className="muted">
              {overrideOf(publication, field) === null
                ? "Using content value"
                : "Customized"}
            </span>
          </dt>
          <dd>
            {displayValue(publication[field]) ?? (
              <span className="muted">{EMPTY_LABELS[field]}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

interface FieldState {
  custom: boolean;
  text: string;
}

function initialFieldState(
  publication: Publication,
  field: MetadataField,
): FieldState {
  const override = overrideOf(publication, field);
  return {
    custom: override !== null,
    text: displayValue(override ?? publication[field]) ?? "",
  };
}

function MetadataForm({
  publication,
  onChanged,
}: {
  publication: Publication;
  onChanged: () => Promise<void>;
}) {
  const id = useId();
  const [fields, setFields] = useState<Record<MetadataField, FieldState>>({
    title: initialFieldState(publication, "title"),
    description: initialFieldState(publication, "description"),
    hashtags: initialFieldState(publication, "hashtags"),
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  function setField(field: MetadataField, changes: Partial<FieldState>) {
    setFields((current) => ({
      ...current,
      [field]: { ...current[field], ...changes },
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const changes: PublicationUpdate = {};
    const { title, description, hashtags } = fields;
    const wanted = {
      title_override: title.custom ? title.text : null,
      description_override: description.custom ? description.text : null,
      hashtags_override: hashtags.custom ? parseHashtags(hashtags.text) : null,
    };
    for (const key of Object.keys(wanted) as (keyof typeof wanted)[]) {
      if (JSON.stringify(wanted[key]) !== JSON.stringify(publication[key])) {
        Object.assign(changes, { [key]: wanted[key] });
      }
    }
    if (Object.keys(changes).length === 0) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updatePublication(publication.id, changes);
      await onChanged();
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form aria-label="Metadata" onSubmit={handleSubmit} noValidate>
      {(Object.keys(FIELD_LABELS) as MetadataField[]).map((field) => {
        const state = fields[field];
        const inputId = `${id}-${field}`;
        const errorField = `${field}_override`;
        return (
          <div key={field} className="metadata-field">
            {state.custom ? (
              <label htmlFor={inputId}>
                {FIELD_LABELS[field]} <span className="muted">Customized</span>
              </label>
            ) : (
              <span className="field-label">
                {FIELD_LABELS[field]}{" "}
                <span className="muted">Using content value</span>
              </span>
            )}
            {state.custom ? (
              field === "description" ? (
                <textarea
                  id={inputId}
                  rows={3}
                  value={state.text}
                  onChange={(event) =>
                    setField(field, { text: event.target.value })
                  }
                  aria-invalid={
                    error?.fieldMessage(errorField) ? true : undefined
                  }
                />
              ) : (
                <input
                  id={inputId}
                  value={state.text}
                  onChange={(event) =>
                    setField(field, { text: event.target.value })
                  }
                  aria-invalid={
                    error?.fieldMessage(errorField) ? true : undefined
                  }
                />
              )
            ) : (
              <p>
                {displayValue(publication[field]) ?? (
                  <span className="muted">{EMPTY_LABELS[field]}</span>
                )}
              </p>
            )}
            <FieldMessage error={error} field={errorField} />
            <div className="actions">
              {state.custom ? (
                <button
                  type="button"
                  onClick={() => setField(field, { custom: false })}
                >
                  Use content value for {FIELD_LABELS[field].toLowerCase()}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    setField(field, {
                      custom: true,
                      text: displayValue(publication[field]) ?? "",
                    })
                  }
                >
                  Customize {FIELD_LABELS[field].toLowerCase()}
                </button>
              )}
            </div>
          </div>
        );
      })}
      <FormError
        error={error}
        fields={["title_override", "description_override", "hashtags_override"]}
      />
      <div className="actions">
        <button type="submit" disabled={saving}>
          Save metadata
        </button>
      </div>
    </form>
  );
}

export default PublicationDetail;
