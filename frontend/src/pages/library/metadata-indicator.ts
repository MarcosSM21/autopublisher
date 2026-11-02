import type { Content } from "../../types.ts";
import type { Tone } from "../../ui/Badge.tsx";
import type { IconName } from "../../ui/Icon.tsx";

export interface MetadataIndicator {
  tone: Extract<Tone, "success" | "warning">;
  icon: Extract<IconName, "check" | "alert">;
  label: "Metadata cleaned" | "Metadata not cleaned";
  reason: string;
  /** Whether Clean metadata is offered (it would create or regenerate a copy). */
  canClean: boolean;
}

const CLEANED = {
  tone: "success",
  icon: "check",
  label: "Metadata cleaned",
} as const;
const NOT_CLEANED = {
  tone: "warning",
  icon: "alert",
  label: "Metadata not cleaned",
} as const;

/**
 * Whether AutoPublisher has run its cleaning on this Media and the file Posts
 * send is there (data-model.md). Derived only from what the API already returns;
 * the one place that turns the metadata state into what the UI shows.
 */
export function metadataIndicator(
  content: Pick<Content, "metadata_status" | "publish_file">,
): MetadataIndicator {
  const available = content.publish_file.available;
  switch (content.metadata_status) {
    case "clean":
      return available
        ? { ...CLEANED, reason: "Already clean", canClean: false }
        : { ...NOT_CLEANED, reason: "Media file missing", canClean: false };
    case "sanitized":
      return available
        ? { ...CLEANED, reason: "Cleaned copy", canClean: false }
        : { ...NOT_CLEANED, reason: "Clean copy missing", canClean: true };
    default:
      return { ...NOT_CLEANED, reason: "Not cleaned yet", canClean: true };
  }
}
