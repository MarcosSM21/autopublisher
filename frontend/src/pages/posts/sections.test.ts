import { describe, expect, it } from "vitest";
import type { Overview, PostDisplayState } from "../../types.ts";
import { readinessSource } from "./readiness.ts";
import {
  dailySections,
  filterPosts,
  historyGroups,
  sectionOf,
} from "./sections.ts";
import { post } from "./test-posts.ts";

const NOW = new Date(2026, 9, 19, 10, 0);
const at = (days: number, hours = 0) =>
  new Date(NOW.getTime() + days * 86_400_000 + hours * 3_600_000).toISOString();

const empty = readinessSource(null, [], NOW);

describe("every display state goes to exactly one section", () => {
  it.each<[PostDisplayState, string]>([
    ["draft", "drafts"],
    ["scheduled_automatic", "upcoming"],
    ["scheduled_manual", "upcoming"],
    ["scheduled_paused", "upcoming"],
    ["publishing", "upcoming"],
    ["published", "history"],
    ["cancelled", "history"],
    ["failed", "needs_you"],
    ["needs_review", "needs_you"],
    ["needs_action", "needs_you"],
    ["missed", "needs_you"],
  ])("%s → %s", (state, section) => {
    expect(sectionOf(post(state, { scheduled_at: at(1) }), empty)).toBe(
      section,
    );
  });

  it("a scheduled Post with a known problem within 7 days needs you", () => {
    const overview = {
      attention: [{ kind: "incomplete", post: { id: 1 }, detail: "Missing" }],
    } as unknown as Overview;
    const health = [
      {
        account_id: 9,
        is_active: true,
        state: "reconnect_needed",
        issue: null,
      },
    ] as never;
    const source = readinessSource(overview, health, NOW);
    expect(
      sectionOf(
        post("scheduled_automatic", { id: 1, scheduled_at: at(2) }),
        source,
      ),
    ).toBe("needs_you");
    expect(
      sectionOf(
        post("scheduled_paused", { id: 2, account_id: 9, scheduled_at: at(2) }),
        source,
      ),
    ).toBe("needs_you");
    // Beyond the horizon nothing is promised: Upcoming.
    expect(
      sectionOf(
        post("scheduled_automatic", { id: 1, scheduled_at: at(9) }),
        source,
      ),
    ).toBe("upcoming");
  });
});

it("orders Needs you by severity, then date; Upcoming by day with Publishing now apart", () => {
  const posts = [
    post("missed", { id: 1, scheduled_at: at(-1) }),
    post("failed", { id: 2, scheduled_at: at(-2) }),
    post("needs_action", { id: 3, updated_at: at(-3) }),
    post("needs_review", { id: 4, scheduled_at: at(-1) }),
    post("failed", { id: 5, scheduled_at: at(-3) }),
    post("scheduled_automatic", { id: 6, scheduled_at: at(1, 2) }),
    post("scheduled_manual", { id: 7, scheduled_at: at(0, 3) }),
    post("scheduled_paused", { id: 8, scheduled_at: at(4) }),
    post("publishing", { id: 9 }),
    post("draft", { id: 10, updated_at: at(-5) }),
    post("draft", { id: 11, updated_at: at(-1) }),
    post("published", { id: 12 }),
  ];
  const sections = dailySections(posts, empty);
  expect(sections.needsYou.map((item) => item.id)).toEqual([4, 5, 2, 1, 3]);
  expect(sections.publishing.map((item) => item.id)).toEqual([9]);
  expect(
    sections.upcoming.map((group) => [
      group.label,
      group.posts.map((p) => p.id),
    ]),
  ).toEqual([
    ["Today", [7]],
    ["Tomorrow", [6]],
    [expect.any(String), [8]],
  ]);
  expect(sections.drafts.map((item) => item.id)).toEqual([11, 10]);
});

it("History holds only Published and Cancelled, newest first by month, with a limit", () => {
  const posts = [
    post("published", { id: 1, published_at: "2026-09-03T10:00:00Z" }),
    post("cancelled", { id: 2, updated_at: "2026-10-02T10:00:00Z" }),
    post("published", { id: 3, published_at: "2026-10-05T10:00:00Z" }),
    post("draft", { id: 4 }),
  ];
  const { groups, total } = historyGroups(posts, 2);
  expect(total).toBe(3);
  expect(groups.map((group) => group.posts.map((p) => p.id))).toEqual([[3, 2]]);
  expect(historyGroups(posts, 30).groups).toHaveLength(2);
});

it("filters by words over caption, hashtags and account, and by destination", () => {
  const posts = [
    post("draft", { id: 1, description: "Summer teaser", hashtags: ["beach"] }),
    post("draft", {
      id: 2,
      description: "Winter",
      account_id: 6,
      account: {
        id: 6,
        platform: "telegram",
        handle: "news",
        display_name: null,
        is_active: true,
      },
    }),
  ];
  expect(filterPosts(posts, "summer #beach", null).map((p) => p.id)).toEqual([
    1,
  ]);
  expect(filterPosts(posts, "telegram", null).map((p) => p.id)).toEqual([2]);
  expect(filterPosts(posts, "", 6).map((p) => p.id)).toEqual([2]);
});
