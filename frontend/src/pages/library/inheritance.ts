import {
  platformLabel,
  type AssetPublication,
  type PostDisplayState,
} from "../../types.ts";

export type MediaTextField = "title" | "description" | "hashtags";

/** States whose text can no longer change (they are history). */
const SETTLED: PostDisplayState[] = ["published", "cancelled"];
const ARMED: PostDisplayState[] = ["scheduled_automatic", "scheduled_paused"];
/** The fields a TikTok caption is built from (the title is not sent). */
const CAPTION_FIELDS: MediaTextField[] = ["description", "hashtags"];

/**
 * Posts whose text follows the Media for a changed field (plan §12): their
 * override is null (`inherits`) and they are not Published or Cancelled. New
 * 019 drafts carry their own text, so they are never affected.
 */
export function affectedPosts(
  publications: AssetPublication[],
  changed: MediaTextField[],
): AssetPublication[] {
  return publications.filter(
    (publication) =>
      !SETTLED.includes(publication.display_state) &&
      changed.some((field) => publication.inherits[field]),
  );
}

/**
 * Whether saving would leave a TikTok Post that publishes automatically without
 * a valid declaration: its recorded consent covers the caption it inherits and
 * that caption changes.
 */
export function tiktokConsentAffected(
  publications: AssetPublication[],
  changed: MediaTextField[],
): AssetPublication[] {
  const captionChanged = changed.filter((field) =>
    CAPTION_FIELDS.includes(field),
  );
  return affectedPosts(publications, captionChanged).filter(
    (publication) =>
      publication.platform === "tiktok" &&
      ARMED.includes(publication.display_state) &&
      publication.consent_covers_caption,
  );
}

/** "TikTok · @cyber" */
export function destinationLabel(publication: AssetPublication): string {
  return `${platformLabel(publication.platform)} · ${publication.account_name}`;
}
