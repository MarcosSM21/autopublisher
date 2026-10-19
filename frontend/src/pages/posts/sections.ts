// The daily list of Posts by meaning (contracts/ui.md §4): every Post goes to
// exactly one section, from the backend's display state and the readiness the
// overview already computed. History is a separate view.
import type { PostDisplayState, Publication } from "../../types.ts";
import { calendarMoment, dayKey } from "./calendar.ts";
import { hasProblem, readinessOf, type ReadinessSource } from "./readiness.ts";

export type SectionId = "history" | "needs_you" | "upcoming" | "drafts";

export const HISTORY_PAGE_SIZE = 30;

const HISTORY: PostDisplayState[] = ["published", "cancelled"];
const NEEDS_YOU_RANK: Partial<Record<PostDisplayState, number>> = {
  needs_review: 1,
  failed: 2,
  missed: 3,
  needs_action: 4,
};
const PROBLEM_RANK = 6;

export function sectionOf(
  post: Publication,
  readiness: ReadinessSource,
): SectionId {
  const state = post.display_state;
  if (HISTORY.includes(state)) {
    return "history";
  }
  if (
    NEEDS_YOU_RANK[state] !== undefined ||
    hasProblem(readinessOf(post, readiness))
  ) {
    return "needs_you";
  }
  if (state === "publishing" || state.startsWith("scheduled_")) {
    return "upcoming";
  }
  return "drafts";
}

function time(value: string | null): number {
  return value === null ? Number.POSITIVE_INFINITY : new Date(value).getTime();
}

/** When a Post is (or was) due, for ordering. */
function anchor(post: Publication): string | null {
  return calendarMoment(post) ?? post.scheduled_at ?? post.updated_at;
}

export interface DayGroup {
  key: string;
  label: string;
  posts: Publication[];
}

export interface DailySections {
  needsYou: Publication[];
  publishing: Publication[];
  upcoming: DayGroup[];
  drafts: Publication[];
}

/** "Today", "Tomorrow" or the local date. */
export function dayLabel(date: Date, now: Date = new Date()): string {
  const today = dayKey(now);
  const tomorrow = dayKey(
    new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1),
  );
  const key = dayKey(date);
  if (key === today) {
    return "Today";
  }
  if (key === tomorrow) {
    return "Tomorrow";
  }
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

export function dailySections(
  posts: readonly Publication[],
  readiness: ReadinessSource,
): DailySections {
  const result: DailySections = {
    needsYou: [],
    publishing: [],
    upcoming: [],
    drafts: [],
  };
  const scheduled: Publication[] = [];
  for (const post of posts) {
    switch (sectionOf(post, readiness)) {
      case "needs_you":
        result.needsYou.push(post);
        break;
      case "upcoming":
        if (post.display_state === "publishing") {
          result.publishing.push(post);
        } else {
          scheduled.push(post);
        }
        break;
      case "drafts":
        result.drafts.push(post);
        break;
      case "history":
        break;
    }
  }
  const rank = (post: Publication) =>
    NEEDS_YOU_RANK[post.display_state] ?? PROBLEM_RANK;
  result.needsYou.sort(
    (a, b) =>
      rank(a) - rank(b) || time(anchor(a)) - time(anchor(b)) || a.id - b.id,
  );
  scheduled.sort(
    (a, b) => time(a.scheduled_at) - time(b.scheduled_at) || a.id - b.id,
  );
  for (const post of scheduled) {
    const date = new Date(post.scheduled_at!);
    const key = dayKey(date);
    let group = result.upcoming.at(-1);
    if (group?.key !== key) {
      group = { key, label: dayLabel(date, readiness.now), posts: [] };
      result.upcoming.push(group);
    }
    group.posts.push(post);
  }
  result.drafts.sort(
    (a, b) => time(b.updated_at) - time(a.updated_at) || b.id - a.id,
  );
  return result;
}

/** The moment a History Post is filed under: published, or cancelled. */
export function historyMoment(post: Publication): string {
  return post.display_state === "published"
    ? (post.published_at ?? post.updated_at)
    : post.updated_at;
}

export interface MonthGroup {
  key: string;
  label: string;
  posts: Publication[];
}

/** Published and Cancelled, newest first, by month; at most `limit`. */
export function historyGroups(
  posts: readonly Publication[],
  limit: number,
): { groups: MonthGroup[]; total: number } {
  const history = posts
    .filter((post) => HISTORY.includes(post.display_state))
    .sort(
      (a, b) => time(historyMoment(b)) - time(historyMoment(a)) || b.id - a.id,
    );
  const groups: MonthGroup[] = [];
  for (const post of history.slice(0, limit)) {
    const date = new Date(historyMoment(post));
    const key = `${date.getFullYear()}-${date.getMonth()}`;
    let group = groups.at(-1);
    if (group?.key !== key) {
      group = {
        key,
        label: date.toLocaleDateString(undefined, {
          month: "long",
          year: "numeric",
        }),
        posts: [],
      };
      groups.push(group);
    }
    group.posts.push(post);
  }
  return { groups, total: history.length };
}

/** Search (title, caption, hashtags, account) and the destination filter. */
export function filterPosts(
  posts: readonly Publication[],
  query: string,
  accountId: number | null,
): Publication[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return posts.filter((post) => {
    if (accountId !== null && post.account_id !== accountId) {
      return false;
    }
    if (words.length === 0) {
      return true;
    }
    const text = [
      post.title,
      post.content?.title,
      post.content?.original_filename,
      post.description,
      post.hashtags.map((tag) => `#${tag}`).join(" "),
      post.account.handle,
      post.account.display_name,
      post.account.platform,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return words.every((word) => text.includes(word));
  });
}
