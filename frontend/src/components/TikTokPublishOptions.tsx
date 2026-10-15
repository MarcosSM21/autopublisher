import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  confirmTikTokConsent,
  getTikTokCreatorInfo,
  getTikTokOptions,
  saveTikTokOptions,
} from "../api.ts";
import {
  TIKTOK_MODE_LABELS,
  TIKTOK_PRIVACY_LABELS,
  type Publication,
  type TikTokMode,
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
  /** Called with the mode whenever it is loaded or changed. */
  onModeChange?: (mode: TikTokMode | null) => void;
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
const MODES: TikTokMode[] = ["DIRECT_POST", "INBOX_UPLOAD"];
const INBOX_NOTICE =
  "You'll finish the post in TikTok: caption, privacy, sounds and other settings are chosen in TikTok's editor.";

function privacyLabel(level: string): string {
  return TIKTOK_PRIVACY_LABELS[level as TikTokPrivacyLevel] ?? level;
}

function writable(
  options: TikTokPublicationOptions,
): TikTokPublicationOptionsWrite {
  return {
    mode: options.mode,
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
 * How the video is sent to TikTok (no default) and, for Direct Post, the review it
 * requires: who receives the post (Creator Info, read again on every opening), the
 * exact caption, the options chosen by the user (nothing preselected) and the
 * declaration with its explicit consent. Upload to Inbox only sends the video: the
 * user finishes the post in TikTok. Every change is saved at once; nothing is
 * stored in the browser.
 */
function TikTokPublishOptions({
  publication,
  onSaved,
  onModeChange,
}: TikTokPublishOptionsProps) {
  const [options, setOptions] = useState<TikTokPublicationOptions | null>(null);
  const [creator, setCreator] = useState<TikTokCreatorInfo | null>(null);
  const [creatorError, setCreatorError] = useState<string | null>(null);
  // Whether the first Creator Info read finished (successfully or not).
  const [creatorRead, setCreatorRead] = useState(false);
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
        })
        .finally(() => setCreatorRead(true)),
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

  // Creator Info only matters for Direct Post.
  const mode = options?.mode ?? null;
  const loaded = options !== null;
  useEffect(() => {
    if (loaded) {
      onModeChange?.(mode);
    }
  }, [loaded, mode, onModeChange]);
  useEffect(() => {
    if (mode === "DIRECT_POST") {
      void loadCreator();
    }
  }, [loadCreator, mode]);

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

  const modeSelector = (
    <fieldset disabled={readOnly}>
      <legend>How to send this video to TikTok</legend>
      <div role="radiogroup" aria-label="TikTok mode">
        {MODES.map((value) => {
          const { available, reason } = options.modes[value];
          return (
            <span key={value}>
              <label>
                <input
                  type="radio"
                  name={`${id}-mode`}
                  checked={options.mode === value}
                  disabled={readOnly || saving || !available}
                  onChange={() => void save({ mode: value })}
                />
                {TIKTOK_MODE_LABELS[value]}
              </label>
              {reason && <span className="muted"> {reason}</span>}
            </span>
          );
        })}
      </div>
    </fieldset>
  );
  const preview = publication.content && (
    <section aria-label="Video">
      <MediaPreview content={publication.content} large />
    </section>
  );
  const problems = options.problems.length > 0 && (
    <ul className="error" aria-label="TikTok problems">
      {options.problems.map((problem) => (
        <li key={`${problem.code}-${problem.field ?? ""}-${problem.message}`}>
          {problem.message}
        </li>
      ))}
    </ul>
  );
  const errorMessage = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );

  if (options.mode !== "DIRECT_POST") {
    return (
      <div className="tiktok-options">
        {modeSelector}
        {options.mode === "INBOX_UPLOAD" && (
          <p className="notice" role="note">
            {INBOX_NOTICE}
          </p>
        )}
        {preview}
        {problems}
        {errorMessage}
      </div>
    );
  }

  if (!creatorRead) {
    return (
      <div className="tiktok-options">
        {modeSelector}
        <p className="muted" role="status">
          Reading the TikTok account…
        </p>
      </div>
    );
  }

  return (
    <div className="tiktok-options">
      {modeSelector}
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

      {preview}

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

      {problems}
      {errorMessage}
    </div>
  );
}

export default TikTokPublishOptions;
