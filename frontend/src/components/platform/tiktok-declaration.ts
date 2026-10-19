import { useState } from "react";
import type { TikTokPublicationOptions } from "../../types.ts";

/**
 * The TikTok declaration accepted for one action (research R-05): exactly the
 * options fingerprint and declaration version that were on screen. It lives
 * only in React state and is recorded (`tiktok-consent`) by the owner of the
 * action right before it runs, never when the box is checked.
 */
export interface DeclarationAcceptance {
  fingerprint: string;
  version: string;
}

type DeclarationOptions = Pick<
  TikTokPublicationOptions,
  "fingerprint" | "declaration"
>;

/**
 * Derived, not stored: any change that produces a new fingerprint (an option or
 * the caption) or a new declaration version unchecks it on its own.
 */
export function isDeclarationAccepted(
  accepted: DeclarationAcceptance | null,
  options: DeclarationOptions | null,
): boolean {
  return (
    accepted !== null &&
    options !== null &&
    options.fingerprint !== null &&
    accepted.fingerprint === options.fingerprint &&
    accepted.version === options.declaration.version
  );
}

/** What checking the box accepts; null while the options are incomplete. */
export function acceptanceFor(
  options: DeclarationOptions,
): DeclarationAcceptance | null {
  return options.fingerprint === null
    ? null
    : {
        fingerprint: options.fingerprint,
        version: options.declaration.version,
      };
}

export interface DeclarationControl {
  accepted: DeclarationAcceptance | null;
  onChange: (accepted: DeclarationAcceptance | null) => void;
}

/**
 * The declaration state of one action. It starts unchecked on every mount,
 * whatever consent the backend has persisted.
 */
export function useTikTokDeclaration(): DeclarationControl {
  const [accepted, setAccepted] = useState<DeclarationAcceptance | null>(null);
  return { accepted, onChange: setAccepted };
}
