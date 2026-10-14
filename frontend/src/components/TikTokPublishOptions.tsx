import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  confirmTikTokConsent,
  getTikTokCreatorInfo,
  getTikTokOptions,
  saveTikTokOptions,
} from "../api.ts";
import {
  TIKTOK_PRIVACY_LABELS,
  type Publication,
  type TikTokCreatorInfo,
  type TikTokPrivacyLevel,
  type TikTokPublicationOptions,
  type TikTokPublicationOptionsWrite,
} from "../types.ts";
import { formatDate, tiktokCaptionLength, toApiError } from "../utils.ts";
import MediaPreview from "./MediaPreview.tsx";

interface TikTokPublishOptionsProps {
  publication: Publication;
  /** Called after saving options or the consent, e.g. to reload the check. */
  onSaved: () => void;
}

const UNAUDITED_REASON =
  "This TikTok app is not audited: TikTok only allows private (Only me) posts.";
const DISCLOSURE_INCOMPLETE =
  "You need to indicate if your content promotes yourself, a third party, or both.";
const DISABLED_INTERACTION_REASON =
  "turned off in this TikTok account's settings";
const INTERACTIONS = [
  { key: "allow_comment", flag: "comment_disabled", label: "Allow comments" },
  { key: "allow_duet", flag: "duet_disabled", label: "Allow duet" },
  { key: "allow_stitch", flag: "stitch_disabled", label: "Allow stitch" },
] as const;

function privacyLabel(level: string): string {
  return TIKTOK_PRIVACY_LABELS[level as TikTokPrivacyLevel] ?? level;
}

function writable(
  options: TikTokPublicationOptions,
): TikTokPublicationOptionsWrite {
  return {
    privacy_level: options.privacy_level,
    allow_comment: options.allow_comment,
    allow_duet: options.allow_duet,
    allow_stitch: options.allow_stitch,
    commercial_disclosure_enabled: options.commercial_disclosure_enabled,
    brand_organic_toggle: options.brand_organic_toggle,
    brand_content_toggle: options.brand_content_toggle,
    is_aigc: options.is_aigc,
  };
}

/**
 * The TikTok review required for Direct Post: who receives the post (Creator Info,
 * read again on every opening), the exact caption, the options chosen by the user
 * (nothing preselected) and the declaration with its explicit consent. Every
 * change is saved at once; nothing is stored in the browser.
 */
function TikTokPublishOptions({
  publication,
  onSaved,
}: TikTokPublishOptionsProps) {
  const [options, setOptions] = useState<TikTokPublicationOptions | null>(null);
  const [creator, setCreator] = useState<TikTokCreatorInfo | null>(null);
  const [creatorError, setCreatorError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Latest values sent, so quick successive changes never overwrite each other.
  const latest = useRef<TikTokPublicationOptionsWrite | null>(null);
  const id = useId();

  // A fresh read on every opening and on Refresh; never polled nor cached.
  const loadCreator = useCallback(
    () =>
      getTikTokCreatorInfo(publication.id)
        .then((loaded) => {
          setCreator(loaded);
          setCreatorError(null);
        })
        .catch((caught: unknown) => {
          setCreator(null);
          setCreatorError(toApiError(caught).message);
        }),
    [publication.id],
  );

  useEffect(() => {
    let active = true;
    getTikTokOptions(publication.id)
      .then((loaded) => {
        if (active) {
          latest.current = writable(loaded);
          setOptions(loaded);
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

  useEffect(() => {
    void loadCreator();
  }, [loadCreator]);

  if (options === null) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : null;
  }

  const readOnly = !options.editable;
  const allowed = new Set<string>(options.allowed_privacy_levels);
  const consentValid = options.consent.state === "valid";

  async function save(changes: Partial<TikTokPublicationOptionsWrite>) {
    if (latest.current === null) {
      return;
    }
    setSaving(true);
    setError(null);
    const values = { ...latest.current, ...changes };
    if (!values.commercial_disclosure_enabled) {
      values.brand_organic_toggle = false;
      values.brand_content_toggle = false;
    }
    latest.current = values;
    try {
      setOptions(await saveTikTokOptions(publication.id, values));
      onSaved();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  async function confirm() {
    if (options === null || options.fingerprint === null) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      setOptions(
        await confirmTikTokConsent(
          publication.id,
          options.fingerprint,
          options.declaration.version,
        ),
      );
      onSaved();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="tiktok-options">
      <section aria-label="TikTok account">
        <h4>Posting to TikTok</h4>
        {creator && creator.can_post && (
          <p className="tiktok-creator">
            {creator.avatar_url && (
              <img
                src={creator.avatar_url}
                alt="TikTok avatar"
                width={40}
                height={40}
                referrerPolicy="no-referrer"
              />
            )}
            <strong>{creator.nickname}</strong>
            {creator.username && (
              <span className="muted"> @{creator.username}</span>
            )}
          </p>
        )}
        {creator?.blocked && (
          <p className="error" role="alert">
            {creator.blocked.message}
          </p>
        )}
        {creator && creator.max_video_post_duration_sec !== null && (
          <p className="muted">
            This account can post videos of up to{" "}
            {creator.max_video_post_duration_sec} seconds
            {creator.video_within_max_duration === false &&
              "; this video is longer"}
            .
          </p>
        )}
        {creator?.account_appears_public && (
          <p className="notice" role="status">
            Your TikTok account appears to be public; set it to private before
            publishing (this TikTok app can only post to private accounts).
          </p>
        )}
        {creatorError && (
          <p className="error" role="alert">
            {creatorError}
          </p>
        )}
        <button type="button" onClick={() => void loadCreator()}>
          Refresh
        </button>
        <p className="muted">
          {UNAUDITED_REASON} Your TikTok account must be private when posting.
        </p>
        <p className="muted">
          TikTok may take a few minutes to process the video before it appears
          on your profile.
        </p>
      </section>

      {options.integrity_warning && (
        <p className="error" role="alert">
          {options.integrity_warning.message} (
          {formatDate(options.integrity_warning.at)})
        </p>
      )}

      {publication.content && (
        <section aria-label="Video">
          <MediaPreview content={publication.content} large />
        </section>
      )}

      <section aria-label="Caption">
        <h4>Caption sent to TikTok</h4>
        {options.caption ? (
          <pre className="caption">{options.caption}</pre>
        ) : (
          <p className="muted">(no caption)</p>
        )}
        <p className="muted">
          <span>
            {tiktokCaptionLength(options.caption)}/{options.caption_max_length}
          </span>{" "}
          characters as TikTok counts them (emoji count as 2). The title is not
          sent and the caption is never shortened; edit the description or
          hashtags to change it.
        </p>
      </section>

      <fieldset disabled={readOnly}>
        <legend>Privacy</legend>
        <label htmlFor={`${id}-privacy`}>Who can view this video</label>
        <select
          id={`${id}-privacy`}
          value={options.privacy_level ?? ""}
          disabled={readOnly || creator?.privacy_level_options == null}
          onChange={(event) =>
            void save({
              privacy_level: (event.target.value ||
                null) as TikTokPrivacyLevel | null,
            })
          }
        >
          <option value="" disabled>
            Choose who can view this video
          </option>
          {(creator?.privacy_level_options ?? []).map((level) => (
            <option key={level} value={level} disabled={!allowed.has(level)}>
              {privacyLabel(level)}
              {!allowed.has(level) && " — not available (app not audited)"}
            </option>
          ))}
        </select>
        <span className="muted">{UNAUDITED_REASON}</span>
      </fieldset>

      <fieldset disabled={readOnly}>
        <legend>Interactions</legend>
        {INTERACTIONS.map(({ key, flag, label }) => {
          const disabledByTikTok = creator?.[flag] === true;
          return (
            <span key={key}>
              <label>
                <input
                  type="checkbox"
                  checked={options[key]}
                  disabled={readOnly || disabledByTikTok}
                  onChange={(event) =>
                    void save({ [key]: event.target.checked })
                  }
                />
                {label}
              </label>
              {disabledByTikTok && (
                <span className="muted">
                  {" "}
                  ({label.replace("Allow ", "")} is{" "}
                  {DISABLED_INTERACTION_REASON})
                </span>
              )}
            </span>
          );
        })}
      </fieldset>

      <fieldset disabled={readOnly}>
        <legend>Commercial content</legend>
        <label>
          <input
            type="checkbox"
            checked={options.commercial_disclosure_enabled}
            onChange={(event) =>
              void save({ commercial_disclosure_enabled: event.target.checked })
            }
          />
          Disclose commercial content
        </label>
        {options.commercial_disclosure_enabled && (
          <>
            <label>
              <input
                type="checkbox"
                checked={options.brand_organic_toggle}
                onChange={(event) =>
                  void save({ brand_organic_toggle: event.target.checked })
                }
              />
              Your brand
            </label>
            <label>
              <input
                type="checkbox"
                checked={options.brand_content_toggle}
                disabled={readOnly || options.privacy_level === "SELF_ONLY"}
                onChange={(event) =>
                  void save({ brand_content_toggle: event.target.checked })
                }
              />
              Branded content
            </label>
            {options.privacy_level === "SELF_ONLY" && (
              <span className="muted branded-reason">
                Branded content visibility cannot be set to private. This TikTok
                app is not audited, so it can only post privately.
              </span>
            )}
            {!options.brand_organic_toggle && !options.brand_content_toggle && (
              <span className="error">{DISCLOSURE_INCOMPLETE}</span>
            )}
          </>
        )}
        {options.labels.map((label) => (
          <span key={label} className="muted">
            {label}
          </span>
        ))}
      </fieldset>

      <fieldset disabled={readOnly}>
        <legend>AI-generated content</legend>
        <div role="radiogroup" aria-label="AI-generated">
          {[
            { value: true, label: "Yes" },
            { value: false, label: "No" },
          ].map(({ value, label }) => (
            <label key={label}>
              <input
                type="radio"
                name={`${id}-aigc`}
                checked={options.is_aigc === value}
                onChange={() => void save({ is_aigc: value })}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <section aria-label="Declaration">
        <p>
          {options.declaration.text}{" "}
          {options.declaration.links.map((link) => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noreferrer noopener"
            >
              {link.label}
            </a>
          ))}
        </p>
        <label>
          <input
            type="checkbox"
            checked={consentValid}
            disabled={
              readOnly || saving || consentValid || options.fingerprint === null
            }
            onChange={(event) => event.target.checked && void confirm()}
          />
          I agree to the declaration above for this video, caption and options
        </label>
        {options.consent.state === "stale" && (
          <p className="notice">
            Your changes need a new confirmation: confirm again to publish this
            video.
          </p>
        )}
        {options.consent.state === "stale" &&
          publication.auto_publish_enabled && (
            <p className="notice" role="status">
              This publication is armed but will not be published automatically
              until you confirm the declaration again.
            </p>
          )}
        {consentValid && (
          <>
            <p role="status">
              Consent recorded — matches saved publication metadata
            </p>
            <p className="muted">
              File integrity is rechecked before publishing.
            </p>
          </>
        )}
      </section>

      {options.problems.length > 0 && (
        <ul className="error" aria-label="TikTok problems">
          {options.problems.map((problem) => (
            <li
              key={`${problem.code}-${problem.field ?? ""}-${problem.message}`}
            >
              {problem.message}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default TikTokPublishOptions;
