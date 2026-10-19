import { getYouTubeOptions, saveYouTubeOptions } from "../../api.ts";
import type { YouTubeOptionsInput } from "../../api.ts";
import {
  YOUTUBE_PRIVACY_LABELS,
  type YouTubePrivacy,
  type YouTubePublicationOptions,
} from "../../types.ts";
import ChoiceGroup from "../../ui/ChoiceGroup.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import type { PlatformFormProps } from "./types.ts";
import { usePlatformOptions } from "./usePlatformOptions.ts";
import YesNoChoice from "./YesNoChoice.tsx";

const PRIVACIES: YouTubePrivacy[] = ["private", "unlisted", "public"];

function toWrite(options: YouTubePublicationOptions): YouTubeOptionsInput {
  return {
    privacy_status: options.privacy_status,
    made_for_kids: options.made_for_kids,
    contains_synthetic_media: options.contains_synthetic_media,
    notify_subscribers: options.notify_subscribers,
  };
}

/**
 * YouTube's required declarations first; privacy and notifications under More
 * options. Every choice is saved when it changes.
 */
function YouTubeDetails(props: PlatformFormProps) {
  const { options, loadError, change } = usePlatformOptions({
    ...props,
    load: getYouTubeOptions,
    save: saveYouTubeOptions,
    toWrite,
  });

  if (loadError) {
    return (
      <ErrorState
        title="Couldn't load the YouTube details"
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
      <YesNoChoice
        legend="Made for kids?"
        value={options.made_for_kids}
        disabled={readOnly}
        onChange={(value) => change({ made_for_kids: value })}
      />
      <YesNoChoice
        legend="Altered or synthetic content?"
        value={options.contains_synthetic_media}
        disabled={readOnly}
        onChange={(value) => change({ contains_synthetic_media: value })}
      />
      <Disclosure label="More options">
        <div className="ap-platform-form">
          <ChoiceGroup
            legend="Privacy"
            orientation="horizontal"
            choices={PRIVACIES.map((value) => ({
              value,
              label: YOUTUBE_PRIVACY_LABELS[value],
            }))}
            value={options.privacy_status}
            disabled={readOnly}
            onChange={(value) => change({ privacy_status: value })}
          />
          <p className="ap-meta">
            YouTube may restrict videos uploaded from unverified API projects to
            private.
          </p>
          <label className="ap-check">
            <input
              type="checkbox"
              checked={options.notify_subscribers}
              disabled={readOnly}
              onChange={(event) =>
                change({ notify_subscribers: event.target.checked })
              }
            />
            <span>Notify subscribers</span>
          </label>
        </div>
      </Disclosure>
    </div>
  );
}

export default YouTubeDetails;
