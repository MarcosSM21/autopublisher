import { useEffect, useId, useState, type FormEvent } from "react";
import { getYouTubeOptions, saveYouTubeOptions } from "../api.ts";
import {
  YOUTUBE_PRIVACY_LABELS,
  type Publication,
  type YouTubePrivacy,
  type YouTubePublicationOptions,
} from "../types.ts";
import { toApiError } from "../utils.ts";

interface YouTubePublishOptionsProps {
  publication: Publication;
  /** Called after saving, e.g. to reload the publish check. */
  onSaved: () => void;
}

const PRIVACIES: YouTubePrivacy[] = ["private", "unlisted", "public"];

/** Privacy, audience and disclosure decisions made explicitly before publishing. */
function YouTubePublishOptions({
  publication,
  onSaved,
}: YouTubePublishOptionsProps) {
  const [options, setOptions] = useState<YouTubePublicationOptions | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const id = useId();

  useEffect(() => {
    let active = true;
    getYouTubeOptions(publication.id)
      .then((loaded) => active && setOptions(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [publication.id, publication.status]);

  if (options === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : null;
  }

  const readOnly = !options.editable;

  function change(values: Partial<YouTubePublicationOptions>) {
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
      const result = await saveYouTubeOptions(publication.id, {
        privacy_status: options.privacy_status,
        made_for_kids: options.made_for_kids,
        contains_synthetic_media: options.contains_synthetic_media,
        notify_subscribers: options.notify_subscribers,
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
      aria-label="YouTube options"
      className="youtube-options"
      onSubmit={handleSubmit}
    >
      <fieldset disabled={readOnly}>
        <legend>Privacy</legend>
        {PRIVACIES.map((privacy) => (
          <label key={privacy}>
            <input
              type="radio"
              name={`${id}-privacy`}
              checked={options.privacy_status === privacy}
              onChange={() => change({ privacy_status: privacy })}
            />{" "}
            {YOUTUBE_PRIVACY_LABELS[privacy]}
          </label>
        ))}
      </fieldset>
      <p className="muted">
        YouTube may restrict videos uploaded from unverified API projects to
        private.
      </p>
      <YesNo
        legend="Made for kids"
        name={`${id}-kids`}
        value={options.made_for_kids}
        disabled={readOnly}
        onChange={(value) => change({ made_for_kids: value })}
      />
      <YesNo
        legend="Altered or synthetic content"
        name={`${id}-synthetic`}
        value={options.contains_synthetic_media}
        disabled={readOnly}
        onChange={(value) => change({ contains_synthetic_media: value })}
      />
      <YesNo
        legend="Notify subscribers"
        name={`${id}-notify`}
        value={options.notify_subscribers}
        disabled={readOnly}
        onChange={(value) => change({ notify_subscribers: value })}
      />
      {!readOnly && (
        <div className="actions">
          <button type="submit" disabled={saving}>
            Save YouTube options
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

function YesNo({
  legend,
  name,
  value,
  disabled,
  onChange,
}: {
  legend: string;
  name: string;
  value: boolean | null;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <fieldset disabled={disabled}>
      <legend>{legend}</legend>
      <label>
        <input
          type="radio"
          name={name}
          checked={value === true}
          onChange={() => onChange(true)}
        />{" "}
        Yes
      </label>
      <label>
        <input
          type="radio"
          name={name}
          checked={value === false}
          onChange={() => onChange(false)}
        />{" "}
        No
      </label>
      {value === null && <span className="badge warning">Not declared</span>}
    </fieldset>
  );
}

export default YouTubePublishOptions;
