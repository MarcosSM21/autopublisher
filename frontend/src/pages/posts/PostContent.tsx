import { useState } from "react";
import { updatePublication, type PublicationUpdate } from "../../api.ts";
import type { Publication } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import Field from "../../ui/Field.tsx";
import { parseHashtags, toApiError } from "../../utils.ts";
import { hashtagsText, usesTitle } from "../publish/snapshot.ts";
import { currentFields, sentContent, type SentField } from "./sent-content.ts";

const EDITABLE: Publication["display_state"][] = [
  "draft",
  "scheduled_automatic",
  "scheduled_manual",
  "scheduled_paused",
  "missed",
  "failed",
];

function Fields({ fields }: { fields: SentField[] }) {
  return (
    <dl className="ap-post-content">
      {fields.map((field) => (
        <div key={field.label}>
          <dt>{field.label}</dt>
          <dd className="ap-caption">{field.value || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

interface PostContentProps {
  post: Publication;
  onChanged: (post: Publication) => void;
}

/**
 * The Post's content. Published: what was actually sent, or the current text
 * labelled as such. Before publishing: each field with where it comes from,
 * one Edit and, for a Media Post with its own text, Use the media's caption.
 */
function PostContent({ post, onChanged }: PostContentProps) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(post.title ?? "");
  const [caption, setCaption] = useState(post.description ?? "");
  const [hashtags, setHashtags] = useState(hashtagsText(post.hashtags));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const withTitle = usesTitle(post.account.platform);
  const media = post.content_id !== null;
  const armedTikTok =
    post.account.platform === "tiktok" &&
    post.auto_publish_enabled &&
    post.display_state.startsWith("scheduled_");

  async function save(changes: PublicationUpdate) {
    setSaving(true);
    setError(null);
    try {
      onChanged(await updatePublication(post.id, changes));
      setEditing(false);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  const heading = (
    <h3 id="post-content" className="ap-post-detail__title">
      Content
    </h3>
  );

  if (post.display_state === "published") {
    const sent = sentContent(post);
    return (
      <section
        className="ap-post-detail__section"
        aria-labelledby="post-content"
      >
        {heading}
        {sent.kind === "written_in_tiktok" && (
          <p>You wrote the caption in TikTok.</p>
        )}
        {sent.kind === "current" && (
          <>
            <p className="ap-meta">
              This is the current text. It may differ from what was sent.
            </p>
            <Fields fields={sent.fields} />
          </>
        )}
        {sent.kind === "sent" && (
          <>
            <Fields fields={sent.fields} />
            <Disclosure label="Current text">
              <Fields fields={currentFields(post)} />
            </Disclosure>
          </>
        )}
      </section>
    );
  }

  const provenance = (override: unknown, inherited: string) =>
    override === null && media ? inherited : "Custom text";

  return (
    <section className="ap-post-detail__section" aria-labelledby="post-content">
      {heading}
      {!editing ? (
        <>
          <dl className="ap-post-content">
            {withTitle && (
              <div>
                <dt>Title</dt>
                <dd>{post.title || "—"}</dd>
                <dd className="ap-meta">
                  {provenance(post.title_override, "Uses the media's title")}
                </dd>
              </div>
            )}
            <div>
              <dt>{media ? "Caption" : "Text"}</dt>
              <dd className="ap-caption">{post.description || "—"}</dd>
              <dd className="ap-meta">
                {provenance(
                  post.description_override,
                  "Uses the media's caption",
                )}
              </dd>
            </div>
            <div>
              <dt>Hashtags</dt>
              <dd>{hashtagsText(post.hashtags) || "—"}</dd>
            </div>
          </dl>
          {EDITABLE.includes(post.display_state) && (
            <div className="ap-post-detail__row">
              <Button onClick={() => setEditing(true)}>Edit</Button>
              {media &&
                (post.description_override !== null ||
                  post.hashtags_override !== null) && (
                  <Button
                    variant="ghost"
                    loading={saving}
                    onClick={() =>
                      void save({
                        description_override: null,
                        hashtags_override: null,
                      })
                    }
                  >
                    Use the media's caption
                  </Button>
                )}
            </div>
          )}
        </>
      ) : (
        <form
          className="ap-edit-content"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save({
              description_override: caption,
              hashtags_override: parseHashtags(hashtags),
              ...(withTitle ? { title_override: title } : {}),
            });
          }}
        >
          {withTitle && (
            <Field label="Title">
              {(control) => (
                <input
                  {...control}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              )}
            </Field>
          )}
          <Field label={media ? "Caption" : "Text"}>
            {(control) => (
              <textarea
                {...control}
                rows={4}
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
              />
            )}
          </Field>
          <Field label="Hashtags">
            {(control) => (
              <input
                {...control}
                value={hashtags}
                onChange={(event) => setHashtags(event.target.value)}
              />
            )}
          </Field>
          {armedTikTok && (
            <p className="ap-notice">
              Changing the caption means TikTok won't publish this post
              automatically until you confirm the TikTok declaration again.
            </p>
          )}
          <div className="ap-post-detail__row">
            <Button type="submit" variant="primary" loading={saving}>
              Save
            </Button>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </form>
      )}
      {error && (
        <p className="ap-field__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default PostContent;
