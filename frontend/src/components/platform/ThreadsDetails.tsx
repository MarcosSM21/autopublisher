import {
  getThreadsOptions,
  saveThreadsOptions,
  type ThreadsOptionsInput,
} from "../../api.ts";
import type { ThreadsPublicationOptions } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import AltTextField from "./AltTextField.tsx";
import type { PlatformFormProps } from "./types.ts";
import { usePlatformOptions } from "./usePlatformOptions.ts";

function toWrite(options: ThreadsPublicationOptions): ThreadsOptionsInput {
  return { alt_text: options.alt_text };
}

/** Threads' only option: alt text for images and videos (optional). */
function ThreadsDetails(props: PlatformFormProps) {
  const { options, loadError, change } = usePlatformOptions({
    ...props,
    load: getThreadsOptions,
    save: saveThreadsOptions,
    toWrite,
  });

  if (loadError) {
    return (
      <ErrorState
        title="Couldn't load the Threads details"
        message={loadError}
      />
    );
  }
  if (options === null) {
    return null;
  }
  const hasMedia =
    options.media_kind === "image" || options.media_kind === "video";
  if (!hasMedia) {
    return <p className="ap-meta">Nothing else to choose for Threads.</p>;
  }
  return (
    <div className="ap-platform-form">
      <AltTextField
        saved={options.alt_text}
        maxLength={options.limits.alt_text_characters}
        hint="Describes the media for people who use screen readers (optional)."
        disabled={!options.editable}
        onCommit={(value) => change({ alt_text: value })}
      />
    </div>
  );
}

export default ThreadsDetails;
