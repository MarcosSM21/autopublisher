import { useId } from "react";
import type { TikTokPublicationOptions } from "../../types.ts";
import {
  acceptanceFor,
  isDeclarationAccepted,
  type DeclarationControl,
} from "./tiktok-declaration.ts";
import "./platform.css";

interface TikTokDeclarationProps extends DeclarationControl {
  options: Pick<TikTokPublicationOptions, "fingerprint" | "declaration">;
  /** Id of the checkbox, so an error summary can link to it. */
  id?: string;
  disabled?: boolean;
}

/**
 * TikTok's official declaration with its links and the single checkbox of the
 * action. Checking it records nothing: the owner of the action does, right
 * before publishing or scheduling.
 */
function TikTokDeclaration({
  options,
  accepted,
  onChange,
  id,
  disabled = false,
}: TikTokDeclarationProps) {
  const generated = useId();
  const checkboxId = id ?? generated;
  const hintId = `${checkboxId}-hint`;
  const incomplete = options.fingerprint === null;
  return (
    <div className="ap-tiktok-declaration">
      <p>
        {options.declaration.text}{" "}
        {options.declaration.links.map((link) => (
          <a
            key={link.url}
            className="ap-link"
            href={link.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {link.label}
          </a>
        ))}
      </p>
      <label className="ap-check" htmlFor={checkboxId}>
        <input
          id={checkboxId}
          type="checkbox"
          checked={isDeclarationAccepted(accepted, options)}
          disabled={disabled || incomplete}
          aria-describedby={incomplete ? hintId : undefined}
          onChange={(event) =>
            onChange(event.target.checked ? acceptanceFor(options) : null)
          }
        />
        <span>
          I agree to the declaration above for this video, caption and options
        </span>
      </label>
      {incomplete && (
        <p id={hintId} className="ap-meta">
          Complete the TikTok details first.
        </p>
      )}
    </div>
  );
}

export default TikTokDeclaration;
