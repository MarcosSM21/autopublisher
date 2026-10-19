import type { ReactNode } from "react";
import Field from "../../../ui/Field.tsx";
import { CONTENT_ID, TEXT_ID } from "../final-action.ts";
import type { CommonText } from "../snapshot.ts";

interface CommonContentProps {
  common: CommonText;
  onChange: (common: CommonText) => void;
  disabled: boolean;
  /** A text post: the text is required and there is no Media to prefill it. */
  textPost?: boolean;
  children?: ReactNode;
}

/**
 * The caption and hashtags shared by the selected destinations, prefilled from
 * the Media. Local until Continue: typing here writes nothing. Destinations
 * can be customized below (children).
 */
function CommonContent({
  common,
  onChange,
  disabled,
  textPost = false,
  children,
}: CommonContentProps) {
  return (
    <fieldset
      id={CONTENT_ID}
      tabIndex={-1}
      className="ap-publish-section"
      disabled={disabled}
    >
      <legend className="ap-publish-section__title">Content</legend>
      <p className="ap-field__hint">
        {textPost
          ? "Used for all selected destinations. You can customize each one after Continue."
          : "Used for all selected destinations unless customized."}
      </p>
      <Field
        label={textPost ? "Text" : "Caption"}
        id={textPost ? TEXT_ID : undefined}
        required={textPost}
      >
        {(control) => (
          <textarea
            {...control}
            rows={4}
            value={common.description}
            onChange={(event) =>
              onChange({ ...common, description: event.target.value })
            }
          />
        )}
      </Field>
      <Field
        label="Hashtags"
        hint="Separate them with spaces, e.g. #summer #clip"
      >
        {(control) => (
          <input
            {...control}
            value={common.hashtags}
            onChange={(event) =>
              onChange({ ...common, hashtags: event.target.value })
            }
          />
        )}
      </Field>
      {children}
    </fieldset>
  );
}

export default CommonContent;
