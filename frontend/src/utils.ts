import { ApiError } from "./api.ts";
import { platformLabel, type Account, type Publication } from "./types.ts";

export function toApiError(caught: unknown): ApiError {
  return caught instanceof ApiError
    ? caught
    : new ApiError(0, "unexpected_error", "Something went wrong.");
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

/** A scheduled publication whose time has passed; nothing happens automatically. */
export function isOverdue(
  publication: Pick<Publication, "status" | "scheduled_at">,
  now: Date = new Date(),
): boolean {
  return (
    publication.status === "scheduled" &&
    publication.scheduled_at !== null &&
    new Date(publication.scheduled_at).getTime() < now.getTime()
  );
}

/** Names an account the way the backend does, e.g. "Instagram @l4i4". */
export function accountName(
  account: Pick<Account, "platform" | "handle">,
): string {
  return `${platformLabel(account.platform)} @${account.handle}`;
}
