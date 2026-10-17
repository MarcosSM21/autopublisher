import { useId, useState, type FormEvent } from "react";
import { updateContent, type ApiError } from "../api.ts";
import { MEDIA_TYPE_LABELS, type Content, type Project } from "../types.ts";
import { formatDate, parseHashtags, toApiError } from "../utils.ts";
import { FormError } from "./FormError.tsx";
import { FieldMessage } from "./ProjectForm.tsx";
import AssetFile from "./AssetFile.tsx";
import AssetUsage from "./AssetUsage.tsx";
import MediaPreview from "./MediaPreview.tsx";
import Distribute from "./Distribute.tsx";

interface ContentDetailProps {
  project: Project;
  content: Content;
  onChanged: () => Promise<void>;
  onOpenPosts: (postId?: number) => void;
}

function ContentDetail({
  project,
  content,
  onChanged,
  onOpenPosts,
}: ContentDetailProps) {
  const [editing, setEditing] = useState(false);
  const [preparing, setPreparing] = useState(false);
  return (
    <section aria-label="Content details" className="content-detail">
      <h3>{content.title ?? content.original_filename}</h3>
      <MediaPreview key={content.id} content={content} large />
      {editing ? (
        <MetadataForm
          content={content}
          onSaved={async () => {
            setEditing(false);
            await onChanged();
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className="actions">
          <button type="button" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button
            type="button"
            aria-expanded={preparing}
            onClick={() => setPreparing((value) => !value)}
          >
            Publish…
          </button>
        </div>
      )}
      {preparing && (
        <Distribute
          project={project}
          content={content}
          onOpenPosts={onOpenPosts}
        />
      )}
      <dl>
        <dt>Type</dt>
        <dd>
          <span className="badge">{MEDIA_TYPE_LABELS[content.media_type]}</span>
        </dd>
        <dt>Title</dt>
        <dd>{content.title ?? <span className="muted">No title</span>}</dd>
        <dt>Description</dt>
        <dd>
          {content.description ?? <span className="muted">No description</span>}
        </dd>
        <dt>Hashtags</dt>
        <dd>
          {content.hashtags.length > 0 ? (
            content.hashtags.map((tag) => `#${tag}`).join(" ")
          ) : (
            <span className="muted">No hashtags</span>
          )}
        </dd>
        <dt>Imported</dt>
        <dd>{formatDate(content.created_at)}</dd>
        <dt>Last updated</dt>
        <dd>{formatDate(content.updated_at)}</dd>
      </dl>
      <AssetFile content={content} onChanged={onChanged} />
      <AssetUsage contentId={content.id} />
    </section>
  );
}

function MetadataForm({
  content,
  onSaved,
  onCancel,
}: {
  content: Content;
  onSaved: () => Promise<void>;
  onCancel: () => void;
}) {
  const id = useId();
  const [title, setTitle] = useState(content.title ?? "");
  const [description, setDescription] = useState(content.description ?? "");
  const [hashtags, setHashtags] = useState(
    content.hashtags.map((tag) => `#${tag}`).join(" "),
  );
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await updateContent(content.id, {
        title: title === "" ? null : title,
        description: description === "" ? null : description,
        hashtags: parseHashtags(hashtags),
      });
      await onSaved();
    } catch (caught) {
      setError(toApiError(caught));
      setSaving(false);
    }
  }

  return (
    <form aria-label="Edit content" onSubmit={handleSubmit} noValidate>
      <label htmlFor={`${id}-title`}>Title</label>
      <input
        id={`${id}-title`}
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        aria-invalid={error?.fieldMessage("title") ? true : undefined}
      />
      <FieldMessage error={error} field="title" />
      <label htmlFor={`${id}-description`}>Description</label>
      <textarea
        id={`${id}-description`}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        rows={3}
        aria-invalid={error?.fieldMessage("description") ? true : undefined}
      />
      <FieldMessage error={error} field="description" />
      <label htmlFor={`${id}-hashtags`}>Hashtags</label>
      <input
        id={`${id}-hashtags`}
        value={hashtags}
        onChange={(event) => setHashtags(event.target.value)}
        placeholder="#l4i4 summer reels"
        aria-invalid={error?.fieldMessage("hashtags") ? true : undefined}
      />
      <FieldMessage error={error} field="hashtags" />
      <FormError error={error} fields={["title", "description", "hashtags"]} />
      <div className="actions">
        <button type="submit" disabled={saving}>
          Save
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default ContentDetail;
