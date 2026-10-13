import { useEffect, useId, useState, type FormEvent } from "react";
import { getThreadsOptions, saveThreadsOptions } from "../api.ts";
import type { Publication, ThreadsPublicationOptions } from "../types.ts";
import { toApiError } from "../utils.ts";

interface ThreadsPublishOptionsProps {
  publication: Publication;
  /** Called after saving, e.g. to reload the publish check. */
  onSaved: () => void;
}

const KIND_LABELS = { text: "Text post", image: "Image", video: "Video" };

/**
 * The exact text Threads will receive, its limits and the only Threads option
 * (alt text, images and videos). Nothing is stored in the browser.
 */
function ThreadsPublishOptions({
  publication,
  onSaved,
}: ThreadsPublishOptionsProps) {
  const [options, setOptions] = useState<ThreadsPublicationOptions | null>(
    null,
  );
  const [altText, setAltText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const id = useId();

  useEffect(() => {
    let active = true;
    getThreadsOptions(publication.id)
      .then((loaded) => {
        if (active) {
          setOptions(loaded);
          setAltText(loaded.alt_text ?? "");
        }
      })
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
  const hasMedia =
    options.media_kind === "image" || options.media_kind === "video";
  const limits = options.limits;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const result = await saveThreadsOptions(publication.id, {
        alt_text: altText,
      });
      setOptions(result);
      setAltText(result.alt_text ?? "");
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
      aria-label="Threads options"
      className="threads-options"
      onSubmit={handleSubmit}
    >
      <p>
        <strong>
          {options.media_kind ? KIND_LABELS[options.media_kind] : "Unsupported"}
        </strong>
      </p>
      <section aria-label="Text">
        <h4>Text sent to Threads</h4>
        {options.text ? (
          <pre className="caption">{options.text}</pre>
        ) : (
          <p className="muted">(empty text)</p>
        )}
        <p className="muted">
          {options.text_length}/{limits.text_characters} characters (emoji count
          as several) · {options.text_links}/{limits.text_links} links. The
          title is not sent to Threads and the text is never shortened.
        </p>
        <p className="muted">
          Threads may show the first link as a preview and turn the first
          hashtag into a topic tag; AutoPublisher sends the text exactly as
          shown.
        </p>
      </section>
      {hasMedia && (
        <>
          <fieldset disabled={readOnly}>
            <legend>Alt text</legend>
            <label htmlFor={`${id}-alt`}>
              Describes the media for people who use screen readers (optional)
            </label>
            <textarea
              id={`${id}-alt`}
              value={altText}
              onChange={(event) => {
                setAltText(event.target.value);
                setSaved(false);
              }}
            />
            <span className="muted">
              {altText.length}/{limits.alt_text_characters}
            </span>
          </fieldset>
          <p className="muted">
            {options.media_delivery_configured
              ? "The media is uploaded to temporary private storage so Threads can fetch it, and deleted afterwards."
              : "Temporary media delivery is not configured: images and videos cannot be published yet."}
          </p>
        </>
      )}
      {options.problems.length > 0 && (
        <ul className="error" aria-label="Threads problems">
          {options.problems.map((problem) => (
            <li
              key={`${problem.code}-${problem.field ?? ""}-${problem.message}`}
            >
              {problem.message}
            </li>
          ))}
        </ul>
      )}
      {hasMedia && !readOnly && (
        <div className="actions">
          <button type="submit" disabled={saving}>
            Save Threads options
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

export default ThreadsPublishOptions;
