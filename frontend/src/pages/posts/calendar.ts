// Calendar of Posts (research R-09, plan §14): a local week from Monday, and
// the moment each Post belongs to, from the same list as Posts. Rescheduling
// goes through the existing action dialog (Feature 024).
import type { Publication } from "../../types.ts";
import type { DialogAction } from "./ActionDialog.tsx";

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** The local Monday of the week of `date`. */
export function mondayOf(date: Date): Date {
  const day = startOfDay(date);
  const offset = (day.getDay() + 6) % 7; // Monday 0 … Sunday 6
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() - offset);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** `YYYY-MM-DD` of a local date. */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * `?week=YYYY-MM-DD` → its local Monday (any day of the week is accepted).
 * Missing or invalid → the current week; `valid` says whether to rewrite it.
 */
export function parseWeek(
  param: string | null,
  today: Date = new Date(),
): { monday: Date; valid: boolean } {
  const match = param ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(param) : null;
  if (match) {
    const [year, month, day] = match.slice(1).map(Number);
    const date = new Date(year, month - 1, day);
    if (
      date.getFullYear() === year &&
      date.getMonth() === month - 1 &&
      date.getDate() === day
    ) {
      const monday = mondayOf(date);
      return { monday, valid: dayKey(monday) === param };
    }
  }
  return { monday: mondayOf(today), valid: false };
}

export function addWeeks(monday: Date, weeks: number): Date {
  return new Date(
    monday.getFullYear(),
    monday.getMonth(),
    monday.getDate() + weeks * 7,
  );
}

export function weekDays(monday: Date): Date[] {
  return Array.from(
    { length: 7 },
    (_, index) =>
      new Date(
        monday.getFullYear(),
        monday.getMonth(),
        monday.getDate() + index,
      ),
  );
}

/** e.g. "20 – 26 Oct 2026", in the browser's locale. */
export function formatRange(monday: Date, locale?: string): string {
  const sunday = weekDays(monday)[6];
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).formatRange(monday, sunday);
}

export function timeZoneLabel(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * The moment a Post belongs to (spec FR-069): when it was published, when it
 * is or was scheduled, or when its current or last execution started. Null for
 * Drafts and Cancelled (never shown).
 */
export function calendarMoment(post: Publication): string | null {
  const attempt = post.latest_attempt;
  switch (post.display_state) {
    case "draft":
    case "cancelled":
      return null;
    case "published":
      return post.published_at ?? post.updated_at;
    case "scheduled_automatic":
    case "scheduled_manual":
    case "scheduled_paused":
    case "missed":
      return post.scheduled_at;
    case "publishing":
      // The execution actually happening: a Publish now of a Post scheduled for
      // later shows when it started, not its old date.
      if (attempt?.trigger === "scheduled" && post.scheduled_at) {
        return post.scheduled_at;
      }
      return attempt?.started_at ?? post.updated_at;
    case "failed":
    case "needs_review":
      if (attempt?.trigger === "scheduled" && post.scheduled_at) {
        return post.scheduled_at;
      }
      return attempt?.started_at ?? post.scheduled_at ?? post.updated_at;
    case "needs_action":
      return attempt?.finished_at ?? post.updated_at;
  }
}

export interface CalendarDay {
  date: Date;
  key: string;
  posts: { post: Publication; at: Date }[];
}

/** The 7 days of the week with their Posts by time (no Drafts or Cancelled). */
export function postsByDay(
  posts: readonly Publication[],
  monday: Date,
): CalendarDay[] {
  const days = weekDays(monday).map((date) => ({
    date,
    key: dayKey(date),
    posts: [] as { post: Publication; at: Date }[],
  }));
  const start = monday.getTime();
  const end = addWeeks(monday, 1).getTime();
  for (const post of posts) {
    const moment = calendarMoment(post);
    if (moment === null) {
      continue;
    }
    const at = new Date(moment);
    if (at.getTime() < start || at.getTime() >= end) {
      continue;
    }
    days.find((day) => day.key === dayKey(at))?.posts.push({ post, at });
  }
  for (const day of days) {
    day.posts.sort(
      (a, b) => a.at.getTime() - b.at.getTime() || a.post.id - b.post.id,
    );
  }
  return days;
}

export function isToday(date: Date, now: Date = new Date()): boolean {
  return dayKey(date) === dayKey(now);
}

/**
 * The schedule action Calendar offers for a Post (Feature 024, research R6):
 * Edit schedule while it is scheduled, Reschedule after a missed or failed
 * start, nothing otherwise. Presentation only: the backend decides.
 */
export function scheduleAction(
  post: Publication,
): Extract<DialogAction, "edit_schedule" | "reschedule"> | null {
  switch (post.display_state) {
    case "scheduled_automatic":
    case "scheduled_paused":
    case "scheduled_manual":
      return "edit_schedule";
    case "missed":
    case "failed":
      return "reschedule";
    default:
      return null;
  }
}
