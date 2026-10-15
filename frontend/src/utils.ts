import { ApiError } from "./api.ts";
import {
  platformLabel,
  PUBLICATION_STATUS_LABELS,
  TEXT_POST_PLATFORMS,
  type Account,
  type Publication,
  type PublicationAttempt,
} from "./types.ts";

export function toApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(0, "unexpected_error", "Something went wrong.");
}

/**
 * Status label of a publication; a TikTok publication awaiting user action is
 * "Ready in TikTok" (the video waits in the TikTok inbox).
 */
export function publicationStatusLabel(
  publication: Pick<Publication, "status" | "account">,
): string {
  if (
    publication.status === "awaiting_user_action" &&
    publication.account.platform === "tiktok"
  ) {
    return "Ready in TikTok";
  }
  return PUBLICATION_STATUS_LABELS[publication.status];
}

export function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

const BYTE_UNITS = ["B", "KB", "MB", "GB"];

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}`
    : `${minutes}:${secs}`;
}

/**
 * TikTok's caption count ("2200 UTF-16 runes"): UTF-16 code units, which is what
 * `String.length` counts. Must match `tiktok_caption_length` in the backend.
 */
export function tiktokCaptionLength(caption: string): number {
  return caption.length;
}

/** Splits free text into hashtags; normalization is done by the backend. */
export function parseHashtags(text: string): string[] {
  return text.split(/[\s,]+/).filter((part) => part.length > 0);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Formats an ISO instant for a datetime-local input, in local time. */
export function toDateTimeLocalValue(iso: string): string {
  const date = new Date(iso);
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Turns a datetime-local value (local time) into an ISO instant in UTC. */
export function fromDateTimeLocalValue(value: string): string {
  return new Date(value).toISOString();
}

/** Whether an ISO instant is still ahead. */
export function isFuture(
  value: string | null,
  now: Date = new Date(),
): boolean {
  return value !== null && new Date(value).getTime() > now.getTime();
}

/** How often an armed publication waiting for the scheduler is reloaded. */
export const AUTOMATION_POLL_INTERVAL_MS = 15_000;

/** Armed scheduled publication that the scheduler may still start by itself. */
export function awaitsAutomaticStart(
  publication: Pick<Publication, "auto_publish_state">,
): boolean {
  return (
    publication.auto_publish_state === "waiting" ||
    publication.auto_publish_state === "due" ||
    publication.auto_publish_state === "paused"
  );
}

/**
 * An armed scheduled publication that missed its automatic window (derived by the
 * backend; the status stays "scheduled"). Disarmed publications are never overdue.
 */
export function isOverdue(
  publication: Pick<Publication, "auto_publish_state">,
): boolean {
  return publication.auto_publish_state === "overdue";
}

/** Names an account the way the backend does, e.g. "Instagram @l4i4". */
export function accountName(
  account: Pick<Account, "platform" | "handle">,
): string {
  return `${platformLabel(account.platform)} @${account.handle}`;
}

export const TEXT_POST_LABEL = "Text post";

/** Active accounts that can publish a post without media. */
export function textPostAccounts(accounts: Account[]): Account[] {
  return accounts.filter(
    (account) =>
      account.is_active && TEXT_POST_PLATFORMS.includes(account.platform),
  );
}

/** The start of a text post, on one line. */
export function textStart(text: string | null, max = 60): string {
  const line = (text ?? "").replace(/\s+/g, " ").trim();
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}

/** How a publication is named: its content, or the start of its text. */
export function publicationTitle(
  publication: Pick<Publication, "content" | "description">,
): string {
  if (publication.content) {
    return publication.content.title ?? publication.content.original_filename;
  }
  return textStart(publication.description) || TEXT_POST_LABEL;
}

/**
 * Percentage shown for an attempt: 100 only once it succeeded, never while it is
 * still running (the backend already caps unfinished attempts at 0.99).
 */
export function attemptPercent(
  attempt: Pick<PublicationAttempt, "status" | "progress">,
): number {
  const percent = Math.round(attempt.progress * 100);
  return attempt.status === "succeeded" ? percent : Math.min(percent, 99);
}

/** Stages in which the platform works and no real percentage exists. */
export function isPlatformStage(
  attempt: Pick<PublicationAttempt, "stage">,
): boolean {
  return attempt.stage === "processing" || attempt.stage === "finalizing";
}

/** What a running attempt is doing, in the words of its platform. */
export function attemptPhaseLabel(
  attempt: Pick<PublicationAttempt, "stage" | "platform">,
): string {
  const platform = platformLabel(attempt.platform);
  switch (attempt.stage) {
    case "preparing":
      return "Preparing";
    case "uploading":
      return "Uploading";
    case "processing":
      return `Processing on ${platform}`;
    case "finalizing":
      // TikTok is already publishing after the last chunk: only its status says
      // when it is done.
      return attempt.platform === "tiktok"
        ? "TikTok is processing the video"
        : `Publishing on ${platform}`;
    case "final_chunk":
      return "Finishing upload";
    case "done":
      return "Done";
  }
}
