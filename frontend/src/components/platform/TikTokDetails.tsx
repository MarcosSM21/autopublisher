import { useCallback, useEffect, useState } from "react";
import {
  getTikTokCreatorInfo,
  getTikTokOptions,
  saveTikTokOptions,
} from "../../api.ts";
import {
  TIKTOK_PRIVACY_LABELS,
  type TikTokCreatorInfo,
  type TikTokMode,
  type TikTokPrivacyLevel,
  type TikTokPublicationOptions,
  type TikTokPublicationOptionsWrite,
} from "../../types.ts";
import Button from "../../ui/Button.tsx";
import ChoiceGroup from "../../ui/ChoiceGroup.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { formatDate, tiktokCaptionLength, toApiError } from "../../utils.ts";
import TikTokDeclaration from "./TikTokDeclaration.tsx";
import type { DeclarationControl } from "./tiktok-declaration.ts";
import type { PlatformFormProps } from "./types.ts";
import { usePlatformOptions } from "./usePlatformOptions.ts";
import YesNoChoice from "./YesNoChoice.tsx";

interface TikTokDetailsProps extends PlatformFormProps {
  /** The declaration of the action (state lifted to its owner). */
  declaration: DeclarationControl;
  /** The loaded options, so the owner can tell whether the declaration holds. */
  onOptionsChange?: (options: TikTokPublicationOptions | null) => void;
  /** Id of the declaration checkbox (for error summary links). */
  declarationId?: string;
  /** False where the action's own dialog shows the declaration. */
  showDeclaration?: boolean;
}

const MODE_LABELS: Record<TikTokMode, string> = {
  DIRECT_POST: "Post directly",
  INBOX_UPLOAD: "Send to my TikTok inbox",
};
const MODES: TikTokMode[] = ["DIRECT_POST", "INBOX_UPLOAD"];
const INTERACTIONS = [
  { key: "allow_comment", flag: "comment_disabled", label: "Allow comments" },
  { key: "allow_duet", flag: "duet_disabled", label: "Allow duet" },
  { key: "allow_stitch", flag: "stitch_disabled", label: "Allow stitch" },
] as const;

function toWrite(
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

/** Without commercial disclosure, no brand toggle stays on (013). */
function normalize(
  values: TikTokPublicationOptionsWrite,
): TikTokPublicationOptionsWrite {
  return values.commercial_disclosure_enabled
    ? values
    : { ...values, brand_organic_toggle: false, brand_content_toggle: false };
}

type CreatorState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; info: TikTokCreatorInfo };

/**
 * How the video reaches TikTok first; for Direct Post, the account read from
 * Creator Info, the privacy TikTok allows (never preselected), interactions,
 * commercial content, AI-generated and the declaration of the action. The
 * declaration is never recorded here: the owner of the action does it.
 */
function TikTokDetails({
  declaration,
  onOptionsChange,
  declarationId,
  showDeclaration = true,
  ...props
}: TikTokDetailsProps) {
  const { options, loadError, change } = usePlatformOptions({
    ...props,
    load: getTikTokOptions,
    save: saveTikTokOptions,
    toWrite,
    normalize,
  });
  const [creator, setCreator] = useState<CreatorState>({ status: "loading" });
  const publicationId = props.publication.id;
  const directPost = options?.mode === "DIRECT_POST";

  useEffect(() => {
    onOptionsChange?.(options);
  }, [options, onOptionsChange]);

  // Read once when Direct Post is shown, and again only on Retry.
  const fetchCreator = useCallback(
    () =>
      getTikTokCreatorInfo(publicationId)
        .then((info) => setCreator({ status: "loaded", info }))
        .catch((caught: unknown) =>
          setCreator({ status: "error", message: toApiError(caught).message }),
        ),
    [publicationId],
  );
  useEffect(() => {
    if (directPost) {
      void fetchCreator();
    }
  }, [directPost, fetchCreator]);
  const retryCreator = () => {
    setCreator({ status: "loading" });
    void fetchCreator();
  };

  if (loadError) {
    return (
      <ErrorState
        title="Couldn't load the TikTok details"
        message={loadError}
      />
    );
  }
  if (options === null) {
    return null;
  }
  const readOnly = !options.editable;
  const inboxAvailable = options.modes.INBOX_UPLOAD.available;

  const modeChoice = (
    <ChoiceGroup
      legend="How should this reach TikTok?"
      choices={MODES.map((mode) => ({
        value: mode,
        label: MODE_LABELS[mode],
        description: options.modes[mode].reason ?? undefined,
        disabled: !options.modes[mode].available,
      }))}
      value={options.mode}
      disabled={readOnly}
      onChange={(mode) => change({ mode })}
    />
  );

  if (options.mode !== "DIRECT_POST") {
    return (
      <div className="ap-platform-form">
        {modeChoice}
        {options.mode === "INBOX_UPLOAD" && (
          <p>You'll get a TikTok inbox notification to finish the post.</p>
        )}
      </div>
    );
  }

  if (creator.status === "loading") {
    return (
      <div className="ap-platform-form">
        {modeChoice}
        <Skeleton lines={3} label="Reading the TikTok account…" />
      </div>
    );
  }
  if (creator.status === "error") {
    return (
      <div className="ap-platform-form">
        {modeChoice}
        <ErrorState
          title="Couldn't read the TikTok account"
          message={creator.message}
          onRetry={retryCreator}
        />
        {inboxAvailable && !readOnly && (
          <Button onClick={() => change({ mode: "INBOX_UPLOAD" })}>
            Send to inbox instead
          </Button>
        )}
      </div>
    );
  }

  const info = creator.info;
  const allowed = new Set<string>(options.allowed_privacy_levels);
  const levels = (info.privacy_level_options ?? options.allowed_privacy_levels)
    .filter((level) => allowed.has(level))
    .map((level) => level as TikTokPrivacyLevel);
  const onlyPrivate = levels.length === 1 && levels[0] === "SELF_ONLY";
  const disclosureIncomplete =
    options.commercial_disclosure_enabled &&
    !options.brand_organic_toggle &&
    !options.brand_content_toggle;

  return (
    <div className="ap-platform-form">
      {modeChoice}
      <p>
        Posting as <strong>{info.nickname}</strong>
        {info.username && <span className="ap-meta"> @{info.username}</span>}
      </p>
      {info.blocked && (
        <p className="ap-field__error">{info.blocked.message}</p>
      )}
      {info.account_appears_public && (
        <p className="ap-notice">
          Your TikTok account appears to be public. Set it to private before
          publishing: this TikTok app can only post to private accounts.
        </p>
      )}
      {info.video_within_max_duration === false && (
        <p className="ap-field__error">
          This video is longer than the {info.max_video_post_duration_sec}{" "}
          seconds this account can post.
        </p>
      )}
      {options.integrity_warning && (
        <p className="ap-field__error">
          {options.integrity_warning.message} (
          {formatDate(options.integrity_warning.at)})
        </p>
      )}

      <ChoiceGroup
        legend="Who can view this video?"
        choices={levels.map((level) => ({
          value: level,
          label: TIKTOK_PRIVACY_LABELS[level] ?? level,
        }))}
        value={options.privacy_level}
        disabled={readOnly}
        onChange={(privacy_level) => change({ privacy_level })}
      />
      {onlyPrivate && (
        <p className="ap-meta">
          This TikTok app can only post privately: only you will see the video.
        </p>
      )}

      <YesNoChoice
        legend="AI-generated content?"
        value={options.is_aigc}
        disabled={readOnly}
        onChange={(is_aigc) => change({ is_aigc })}
      />

      <fieldset className="ap-choice-group" disabled={readOnly}>
        <legend className="ap-choice-group__legend">Commercial content</legend>
        <label className="ap-check">
          <input
            type="checkbox"
            checked={options.commercial_disclosure_enabled}
            onChange={(event) =>
              change({ commercial_disclosure_enabled: event.target.checked })
            }
          />
          <span>Disclose commercial content</span>
        </label>
        {options.commercial_disclosure_enabled && (
          <>
            <label className="ap-check">
              <input
                type="checkbox"
                checked={options.brand_organic_toggle}
                onChange={(event) =>
                  change({ brand_organic_toggle: event.target.checked })
                }
              />
              <span>Your brand</span>
            </label>
            <label className="ap-check">
              <input
                type="checkbox"
                checked={options.brand_content_toggle}
                disabled={options.privacy_level === "SELF_ONLY"}
                onChange={(event) =>
                  change({ brand_content_toggle: event.target.checked })
                }
              />
              <span>Branded content</span>
            </label>
            {options.privacy_level === "SELF_ONLY" && (
              <p className="ap-meta">
                Branded content can't be private, and this TikTok app can only
                post privately.
              </p>
            )}
            {disclosureIncomplete && (
              <p className="ap-field__error">
                You need to indicate if your content promotes yourself, a third
                party, or both.
              </p>
            )}
          </>
        )}
        {options.labels.map((label) => (
          <p key={label} className="ap-meta">
            {label}
          </p>
        ))}
      </fieldset>

      <Disclosure label="More options">
        <div className="ap-platform-form">
          <fieldset className="ap-choice-group" disabled={readOnly}>
            <legend className="ap-choice-group__legend">Interactions</legend>
            {INTERACTIONS.map(({ key, flag, label }) => {
              const offInTikTok = info[flag] === true;
              return (
                <label key={key} className="ap-check">
                  <input
                    type="checkbox"
                    checked={options[key]}
                    disabled={offInTikTok}
                    onChange={(event) =>
                      change({ [key]: event.target.checked })
                    }
                  />
                  <span>
                    {label}
                    {offInTikTok && (
                      <span className="ap-meta">
                        {" "}
                        (turned off in this TikTok account's settings)
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </fieldset>
          <div>
            <p className="ap-field__label">Caption sent to TikTok</p>
            <p className="ap-caption">{options.caption || "(no caption)"}</p>
            <p className="ap-meta">
              {tiktokCaptionLength(options.caption)}/
              {options.caption_max_length} characters. The title is not sent and
              the caption is never shortened.
            </p>
          </div>
        </div>
      </Disclosure>

      {showDeclaration && (
        <TikTokDeclaration
          options={options}
          id={declarationId}
          disabled={readOnly}
          {...declaration}
        />
      )}
    </div>
  );
}

export default TikTokDetails;
