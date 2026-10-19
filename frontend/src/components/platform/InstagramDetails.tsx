import {
  getInstagramOptions,
  saveInstagramOptions,
  type InstagramOptionsInput,
} from "../../api.ts";
import type { InstagramPublicationOptions } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import AltTextField from "./AltTextField.tsx";
import type { PlatformFormProps } from "./types.ts";
import { usePlatformOptions } from "./usePlatformOptions.ts";
import YesNoChoice from "./YesNoChoice.tsx";

function toWrite(options: InstagramPublicationOptions): InstagramOptionsInput {
  return {
    is_ai_generated: options.is_ai_generated,
    ...(options.media_kind === "reel"
      ? { share_to_feed: options.share_to_feed ?? true }
      : { alt_text: options.alt_text }),
  };
}

/**
 * Instagram's AI disclosure (required), share to feed for Reels and alt text
 * for images (saved when the field loses focus).
 */
function InstagramDetails(props: PlatformFormProps) {
  const { options, loadError, change } = usePlatformOptions({
    ...props,
    load: getInstagramOptions,
    save: saveInstagramOptions,
    toWrite,
  });

  if (loadError) {
    return (
      <ErrorState
        title="Couldn't load the Instagram details"
        message={loadError}
      />
    );
  }
  if (options === null) {
    return null;
  }
  const readOnly = !options.editable;
  return (
    <div className="ap-platform-form">
      <p className="ap-meta">
        {options.media_kind === "reel" ? "Reel" : "Image post"} · the title is
        not sent to Instagram.
      </p>
      <YesNoChoice
        legend="AI-generated content?"
        value={options.is_ai_generated}
        disabled={readOnly}
        onChange={(value) => change({ is_ai_generated: value })}
      />
      {options.media_kind === "reel" ? (
        <label className="ap-check">
          <input
            type="checkbox"
            checked={options.share_to_feed ?? true}
            disabled={readOnly}
            onChange={(event) =>
              change({ share_to_feed: event.target.checked })
            }
          />
          <span>Also show the Reel in the feed</span>
        </label>
      ) : (
        <AltTextField
          saved={options.alt_text}
          maxLength={options.limits.alt_text_characters}
          hint="Describes the image for people who use screen readers (optional)."
          disabled={readOnly}
          onCommit={(value) => change({ alt_text: value })}
        />
      )}
    </div>
  );
}

export default InstagramDetails;
