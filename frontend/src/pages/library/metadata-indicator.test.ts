import { describe, expect, it } from "vitest";
import type { Content, PublishFile } from "../../types.ts";
import { metadataIndicator } from "./metadata-indicator.ts";

function content(
  metadata_status: Content["metadata_status"],
  available: boolean,
): Pick<Content, "metadata_status" | "publish_file"> {
  const publish_file: PublishFile = {
    version: metadata_status === "sanitized" ? "clean_copy" : "original",
    available,
    checksum: "c",
    size_bytes: 1,
    sanitized_at: null,
  };
  return { metadata_status, publish_file };
}

describe("metadataIndicator", () => {
  it.each([
    [
      "unknown",
      true,
      "warning",
      "alert",
      "Metadata not cleaned",
      "Not cleaned yet",
      true,
    ],
    [
      "unknown",
      false,
      "warning",
      "alert",
      "Metadata not cleaned",
      "Not cleaned yet",
      true,
    ],
    [
      "clean",
      true,
      "success",
      "check",
      "Metadata cleaned",
      "Already clean",
      false,
    ],
    [
      "clean",
      false,
      "warning",
      "alert",
      "Metadata not cleaned",
      "Media file missing",
      false,
    ],
    [
      "sanitized",
      true,
      "success",
      "check",
      "Metadata cleaned",
      "Cleaned copy",
      false,
    ],
    [
      "sanitized",
      false,
      "warning",
      "alert",
      "Metadata not cleaned",
      "Clean copy missing",
      true,
    ],
  ] as const)(
    "%s with the file available=%s → %s",
    (status, available, tone, icon, label, reason, canClean) => {
      expect(metadataIndicator(content(status, available))).toEqual({
        tone,
        icon,
        label,
        reason,
        canClean,
      });
    },
  );
});
