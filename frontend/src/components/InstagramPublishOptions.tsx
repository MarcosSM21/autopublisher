import { useEffect, useId, useState, type FormEvent } from "react";
import { getInstagramOptions, saveInstagramOptions } from "../api.ts";
import type { InstagramPublicationOptions, Publication } from "../types.ts";
import { toApiError } from "../utils.ts";
import { YesNo } from "./YouTubePublishOptions.tsx";

interface InstagramPublishOptionsProps {
  publication: Publication;
  /** Called after saving, e.g. to reload the publish check. */
  onSaved: () => void;
}

/**
 * The exact caption Instagram will receive and the Instagram-only decisions made
 * explicitly before publishing: AI disclosure, share to feed (Reels) and alt text
 * (images). Nothing is stored in the browser.
 */
function InstagramPublishOptions({
  publication,
  onSaved,
}: InstagramPublishOptionsProps) {
  const [options, setOptions] = useState<InstagramPublicationOptions | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const id = useId();

  useEffect(() => {
    let active = true;
    getInstagramOptions(publication.id)
      .then((loaded) => active && setOptions(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [
    publication.id,
    publication.status,
    publication.description,
    publication.hashtags,
  ]);

  if (options === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : null;
  }

  const readOnly = !options.editable;
  const isReel = options.media_kind === "reel";
  const limits = options.limits;

  function change(values: Partial<InstagramPublicationOptions>) {
    setOptions((current) => (current ? { ...current, ...values } : current));
    setSaved(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (options === null) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await saveInstagramOptions(publication.id, {
        is_ai_generated: options.is_ai_generated,
        ...(options.media_kind === "reel"
          ? { share_to_feed: options.share_to_feed ?? true }
          : { alt_text: options.alt_text }),
      });
      setOptions(result);
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
      aria-label="Instagram options"
      className="instagram-options"
      onSubmit={handleSubmit}
    >
      <p>
        <strong>{isReel ? "Reel" : "Image Post"}</strong>
      </p>
      <section aria-label="Caption">
        <h4>Caption sent to Instagram</h4>
        {options.caption ? (
          <pre className="caption">{options.caption}</pre>
        ) : (
          <p className="muted">(empty caption)</p>
        )}
        <p className="muted">
          {options.caption_length}/{limits.caption_characters} characters ·{" "}
          {options.caption_hashtags}/{limits.caption_hashtags} hashtags ·{" "}
          {options.caption_mentions}/{limits.caption_mentions} mentions. The
          title is not sent to Instagram.
        </p>
      </section>
      <YesNo
        legend="AI-generated content"
        name={`${id}-ai`}
        value={options.is_ai_generated}
        disabled={readOnly}
        onChange={(value) => change({ is_ai_generated: value })}
      />
      {isReel ? (
        <fieldset disabled={readOnly}>
          <legend>Share to feed</legend>
          <label>
            <input
              type="checkbox"
              checked={options.share_to_feed ?? true}
              onChange={(event) =>
                change({ share_to_feed: event.target.checked })
              }
            />{" "}
            Also show the Reel in the feed (default: on)
          </label>
        </fieldset>
      ) : (
        <fieldset disabled={readOnly}>
          <legend>Alt text</legend>
          <label htmlFor={`${id}-alt`}>
            Describes the image for people who use screen readers (optional)
          </label>
          <textarea
            id={`${id}-alt`}
            value={options.alt_text ?? ""}
            maxLength={limits.alt_text_characters}
            onChange={(event) => change({ alt_text: event.target.value })}
          />
          <span className="muted">
            {(options.alt_text ?? "").length}/{limits.alt_text_characters}
          </span>
        </fieldset>
      )}
      {options.problems.length > 0 && (
        <ul className="error" aria-label="Instagram problems">
          {options.problems.map((problem) => (
            <li
              key={`${problem.code}-${problem.field ?? ""}-${problem.message}`}
            >
              {problem.message}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div className="actions">
          <button type="submit" disabled={saving}>
            Save Instagram options
          </button>
          {saved && <span role="status">Saved.</span>}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export default InstagramPublishOptions;
