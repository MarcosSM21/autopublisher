import { useId, useState, type FormEvent } from "react";
import { updateContent, type ApiError, type ContentUpdate } from "../../api.ts";
import type { AssetPublication, Content } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
import Field from "../../ui/Field.tsx";
import { parseHashtags, toApiError } from "../../utils.ts";
import {
  affectedPosts,
  destinationLabel,
  tiktokConsentAffected,
  type MediaTextField,
} from "./inheritance.ts";
import InheritanceWarning from "./InheritanceWarning.tsx";

interface MediaContentEditorProps {
  content: Content;
  /** The Media's Posts (usage), null while they load. */
  publications: AssetPublication[] | null;
  onSaved: () => Promise<void> | void;
}

interface Draft {
  title: string;
  description: string;
  hashtags: string;
}

function draftOf(content: Content): Draft {
  return {
    title: content.title ?? "",
    description: content.description ?? "",
    hashtags: content.hashtags.map((tag) => `#${tag}`).join(" "),
  };
}

/** The fields whose value differs from the saved Media, as a PATCH body. */
function changesOf(content: Content, draft: Draft): ContentUpdate {
  const changes: ContentUpdate = {};
  const title = draft.title.trim() === "" ? null : draft.title;
  const description =
    draft.description.trim() === "" ? null : draft.description;
  const hashtags = parseHashtags(draft.hashtags).map((tag) =>
    tag.replace(/^#/, ""),
  );
  if (title !== content.title) {
    changes.title = title;
  }
  if (description !== content.description) {
    changes.description = description;
  }
  if (hashtags.join(" ") !== content.hashtags.join(" ")) {
    changes.hashtags = hashtags;
  }
  return changes;
}

/**
 * The Media's title, caption and hashtags in one block: Edit, then Save or
 * Cancel (no autosave: it is the Media's own text and the inheritance warning
 * needs a deliberate save). While editing, an inline note lists the Posts that
 * follow the Media's text; saving a caption a scheduled TikTok declaration
 * covers asks first.
 */
function MediaContentEditor({
  content,
  publications,
  onSaved,
}: MediaContentEditorProps) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const headingId = useId();

  if (draft === null) {
    return (
      <section className="ap-media-section" aria-labelledby={headingId}>
        <div className="ap-media-section__header">
          <h3 id={headingId} className="ap-media-section__title">
            Content
          </h3>
          <Button
            onClick={() => {
              setError(null);
              setDraft(draftOf(content));
            }}
          >
            Edit
          </Button>
        </div>
        <dl className="ap-media-facts">
          <dt>Title</dt>
          <dd>{content.title ?? <span className="ap-meta">No title</span>}</dd>
          <dt>Caption</dt>
          <dd className="ap-media-facts__text">
            {content.description ?? <span className="ap-meta">No caption</span>}
          </dd>
          <dt>Hashtags</dt>
          <dd>
            {content.hashtags.length > 0 ? (
              content.hashtags.map((tag) => `#${tag}`).join(" ")
            ) : (
              <span className="ap-meta">No hashtags</span>
            )}
          </dd>
        </dl>
      </section>
    );
  }

  const changes = changesOf(content, draft);
  const changed = Object.keys(changes) as MediaTextField[];
  const rows = publications ?? [];
  const affected = affectedPosts(rows, changed);
  const consentAffected = tiktokConsentAffected(rows, changed);

  async function save() {
    setConfirming(false);
    if (changed.length === 0) {
      setDraft(null);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateContent(content.id, changes);
      setDraft(null);
      await onSaved();
    } catch (caught) {
      setError(toApiError(caught));
    } finally {
      setSaving(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (consentAffected.length > 0) {
      setConfirming(true);
      return;
    }
    void save();
  }

  const set = (field: keyof Draft) => (value: string) =>
    setDraft((current) => current && { ...current, [field]: value });
  const fieldError = (field: string) => error?.fieldMessage(field) ?? null;
  const otherError =
    error && !["title", "description", "hashtags"].some(fieldError)
      ? error.message
      : null;

  return (
    <section className="ap-media-section" aria-labelledby={headingId}>
      <h3 id={headingId} className="ap-media-section__title">
        Content
      </h3>
      <form
        className="ap-media-editor"
        aria-label="Edit content"
        noValidate
        onSubmit={handleSubmit}
      >
        <Field label="Title" error={fieldError("title")}>
          {(control) => (
            <input
              {...control}
              value={draft.title}
              onChange={(event) => set("title")(event.target.value)}
            />
          )}
        </Field>
        <Field label="Caption" error={fieldError("description")}>
          {(control) => (
            <textarea
              {...control}
              rows={4}
              value={draft.description}
              onChange={(event) => set("description")(event.target.value)}
            />
          )}
        </Field>
        <Field
          label="Hashtags"
          hint="Separated by spaces, e.g. #summer #reels"
          error={fieldError("hashtags")}
        >
          {(control) => (
            <input
              {...control}
              value={draft.hashtags}
              onChange={(event) => set("hashtags")(event.target.value)}
            />
          )}
        </Field>
        <InheritanceWarning affected={affected} />
        {otherError && (
          <p className="ap-field__error" role="alert">
            {otherError}
          </p>
        )}
        <div className="ap-media-editor__actions">
          <Button type="submit" variant="primary" loading={saving}>
            Save
          </Button>
          <Button
            variant="ghost"
            disabled={saving}
            onClick={() => {
              setDraft(null);
              setError(null);
            }}
          >
            Cancel
          </Button>
        </div>
      </form>
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Change the caption of scheduled TikTok posts?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void save()}>
              Save anyway
            </Button>
          </>
        }
      >
        <p>
          TikTok won't publish these posts automatically until you confirm the
          TikTok declaration again.
        </p>
        <ul>
          {consentAffected.map((publication) => (
            <li key={publication.publication_id}>
              {destinationLabel(publication)}
            </li>
          ))}
        </ul>
      </Dialog>
    </section>
  );
}

export default MediaContentEditor;
