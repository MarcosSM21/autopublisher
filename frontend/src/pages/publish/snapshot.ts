// The content a new Draft keeps (spec FR-028, data-model §4): what the user
// confirmed, saved per destination as explicit overrides, even when it equals
// the Media's value or is empty. Nothing is shortened or adapted here: limits
// stay with the backend (FR-025).
import type { PublicationCreate, PublicationOverrides } from "../../api.ts";
import type { Content, Platform } from "../../types.ts";
import { parseHashtags } from "../../utils.ts";

/** Platforms that send a title (a presentation rule; YouTube today). */
export const TITLE_PLATFORMS: readonly Platform[] = ["youtube"];

export type TextField = "title" | "description" | "hashtags";

/** Compose's local text shared by every selected destination. */
export interface CommonText {
  description: string;
  /** As typed, e.g. "#summer #clip". */
  hashtags: string;
}

/** Only the fields the user changed for one destination. */
export type CustomText = Partial<Record<TextField, string>>;

export interface SnapshotTarget {
  accountId: number;
  platform: Platform;
}

export function usesTitle(platform: Platform): boolean {
  return TITLE_PLATFORMS.includes(platform);
}

export function hashtagsText(tags: readonly string[]): string {
  return tags.map((tag) => `#${tag}`).join(" ");
}

/** Common text prefilled from the Media (empty for a text post). */
export function commonFromMedia(media: Content | null): CommonText {
  return {
    description: media?.description ?? "",
    hashtags: hashtagsText(media?.hashtags ?? []),
  };
}

/** The explicit overrides of one destination. */
export function snapshotFor(
  target: SnapshotTarget,
  common: CommonText,
  custom: CustomText | undefined,
  media: Pick<Content, "title">,
): PublicationOverrides {
  const overrides: PublicationOverrides = {
    description_override: custom?.description ?? common.description,
    hashtags_override: parseHashtags(custom?.hashtags ?? common.hashtags),
  };
  if (usesTitle(target.platform)) {
    overrides.title_override = custom?.title ?? media.title ?? "";
  }
  return overrides;
}

/**
 * The create request of Continue: only `targets[accountId]` with explicit
 * overrides. No common fields, no date, no auto-publish (contracts/api.md §1).
 */
export function buildCreateBody(
  selected: readonly SnapshotTarget[],
  common: CommonText,
  custom: Readonly<Record<number, CustomText>>,
  media: Pick<Content, "title">,
): PublicationCreate {
  const targets: Record<number, PublicationOverrides> = {};
  for (const target of selected) {
    targets[target.accountId] = snapshotFor(
      target,
      common,
      custom[target.accountId],
      media,
    );
  }
  return {
    account_ids: selected.map((target) => target.accountId),
    targets,
  };
}
