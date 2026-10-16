import { useId, useState, type FormEvent } from "react";
import {
  cancelPublication,
  reactivatePublication,
  updatePublication,
  type ApiError,
  type PublicationUpdate,
} from "../api.ts";
import {
  type Publication,
  type PublicationStatus,
  type TikTokMode,
} from "../types.ts";
import {
  accountName,
  formatDate,
  fromDateTimeLocalValue,
  isPublishable,
  isTikTokVideo as isTikTokVideoPublication,
  parseHashtags,
  PUBLISHABLE,
  publicationStatusLabel,
  publicationTitle,
  TEXT_POST_LABEL,
  toApiError,
  toDateTimeLocalValue,
} from "../utils.ts";
import MediaPreview from "./MediaPreview.tsx";
import { FormError } from "./FormError.tsx";
import { FieldMessage } from "./ProjectForm.tsx";
import PublicationAttempts from "./PublicationAttempts.tsx";
import { AutoPublishConsent } from "./AutoPublishConsent.tsx";
import {
  AutoPublishControls,
  PublicationPlatformOptions,
  PublishAction,
} from "./PublicationControls.tsx";
import TikTokInboxDelivery from "./TikTokInboxDelivery.tsx";
import { useLivePublication } from "./useLivePublication.ts";

export { POLL_INTERVAL_MS } from "../utils.ts";

/** Statuses whose date can still be changed. */
const SCHEDULABLE: PublicationStatus[] = ["unscheduled", "scheduled"];

interface PublicationDetailProps {
  publication: Publication;
  /** Reloads the queue; the notice, if any, is shown to the user. */
  onChanged: (notice?: string) => Promise<void>;
}

const DATE_REMOVED_NOTICE =
  "The scheduled date had passed and was removed. Choose a new date.";
const TIKTOK_MODE_REQUIRED = "Choose how to send this video to TikTok.";
const INBOX_SCHEDULE_NOTE =
  "AutoPublisher starts sending at this time; the TikTok inbox notification may arrive later.";

/** Why a publication cannot be scheduled or reactivated, if it cannot. */
function preparationBlocker(publication: Publication): string | null {
  if (!publication.project_active) {
    return "Reactivate the project to schedule this publication.";
  }
  if (!publication.account.is_active) {
    return "Reactivate the account to schedule this publication.";
  }
  // A publication without content has no file to check.
  if (publication.content && !publication.content.file_available) {
    return "The media file of this content is not available.";
  }
  return null;
}

function PublicationDetail({
  publication: initial,
  onChanged,
}: PublicationDetailProps) {
  const { publication, setPublication, handleReconciled } = useLivePublication(
    initial,
    onChanged,
  );
  const cancelled = publication.status === "cancelled";
  const blocker = preparationBlocker(publication);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  // Bumped after saving options so the publish check is loaded again.
  const [checkVersion, setCheckVersion] = useState(0);
  const isTikTokVideo = isTikTokVideoPublication(publication);
  // Undefined until the TikTok options are loaded.
  const [tiktokMode, setTikTokMode] = useState<TikTokMode | null | undefined>(
    undefined,
  );
  const scheduleBlocker =
    blocker ??
    (isTikTokVideo && tiktokMode === null ? TIKTOK_MODE_REQUIRED : null);
  const publishable = isPublishable(publication);

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
      <h3>{publicationTitle(publication)}</h3>
      {publication.content ? (
        <MediaPreview content={publication.content} />
      ) : (
        <p>
          <span className="badge">{TEXT_POST_LABEL}</span>
        </p>
      )}
      <p>
        {accountName(publication.account)}
        <span className={`badge status-${publication.status}`}>
          {publicationStatusLabel(publication)}
        </span>
      </p>

      <PublicationPlatformOptions
        publication={publication}
        onSaved={() => setCheckVersion((version) => version + 1)}
        onModeChange={setTikTokMode}
      />
      {isTikTokVideo && (
        <TikTokInboxDelivery
          publication={publication}
          onChanged={(changed) => {
            setPublication(changed);
            void onChanged();
          }}
        />
      )}
      {publishable && (
        <PublishAction
          sendToTikTok={isTikTokVideo && tiktokMode === "INBOX_UPLOAD"}
          publication={publication}
          checkVersion={checkVersion}
          dialogOpen={dialogOpen}
          onOpen={() => setDialogOpen(true)}
          onCancel={() => setDialogOpen(false)}
          onPublished={handlePublished}
          onReconciled={handleReconciled}
        />
      )}
      <PublicationAttempts
        publication={publication}
        onCheckAgain={() => setCheckVersion((version) => version + 1)}
      />

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
          {publication.status === "scheduled" && (
            <AutoPublishControls
              publication={publication}
              onSaved={(saved) => {
                setPublication(saved);
                void onChanged();
              }}
            />
          )}
          {SCHEDULABLE.includes(publication.status) && (
            <ScheduleForm
              key={`${publication.scheduled_at}-${publication.auto_publish_enabled}`}
              publication={publication}
              blocker={scheduleBlocker}
              note={
                isTikTokVideo && tiktokMode === "INBOX_UPLOAD"
                  ? INBOX_SCHEDULE_NOTE
                  : null
              }
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

function ScheduleForm({
  publication,
  blocker,
  note = null,
  onChanged,
}: {
  publication: Publication;
  blocker: string | null;
  /** What the scheduled time means for this publication, if it needs saying. */
  note?: string | null;
  onChanged: () => Promise<void>;
}) {
  const id = useId();
  const [value, setValue] = useState(
    publication.scheduled_at
      ? toDateTimeLocalValue(publication.scheduled_at)
      : "",
  );
  // The current consent, so saving with it checked is an explicit decision.
  const [autoPublish, setAutoPublish] = useState(
    publication.auto_publish_enabled,
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(scheduledAt: string | null) {
    setSaving(true);
    setError(null);
    try {
      await updatePublication(
        publication.id,
        scheduledAt === null
          ? { scheduled_at: null }
          : { scheduled_at: scheduledAt, auto_publish_enabled: autoPublish },
      );
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
      {value && (
        <AutoPublishConsent
          checked={autoPublish}
          disabled={saving}
          onChange={setAutoPublish}
        />
      )}
      <FieldMessage error={error} field="auto_publish_enabled" />
      <FormError
        error={error}
        fields={["scheduled_at", "auto_publish_enabled"]}
      />
      <div className="actions">
        <button
          type="submit"
          disabled={saving || value === "" || blocker !== null}
        >
          {autoPublish ? "Schedule & enable auto-publish" : "Save schedule"}
        </button>
        {publication.scheduled_at && (
          <button type="button" disabled={saving} onClick={() => save(null)}>
            Remove date
          </button>
        )}
      </div>
      {note && <p className="muted">{note}</p>}
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

/**
 * Editable fields: a publication without content has no title and no content
 * values to fall back to; its description and hashtags are its text.
 */
function metadataFields(publication: Publication): MetadataField[] {
  const fields = Object.keys(FIELD_LABELS) as MetadataField[];
  return publication.content
    ? fields
    : fields.filter((field) => field !== "title");
}

function MetadataSummary({ publication }: { publication: Publication }) {
  return (
    <dl>
      {metadataFields(publication).map((field) => (
        <div key={field}>
          <dt>
            {FIELD_LABELS[field]}{" "}
            {publication.content && (
              <span className="muted">
                {overrideOf(publication, field) === null
                  ? "Using content value"
                  : "Customized"}
              </span>
            )}
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
    // Without content, the publication's own values are always edited.
    custom: override !== null || publication.content === null,
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
      title_override: title.custom && publication.content ? title.text : null,
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
      {metadataFields(publication).map((field) => {
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
              {publication.content === null ? null : state.custom ? (
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
