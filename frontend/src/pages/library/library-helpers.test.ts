import { describe, expect, it } from "vitest";
import type { Content, ContentUsage } from "../../types.ts";
import { filterMedia, type LibraryFilter } from "./library-filters.ts";
import { usageIndicator } from "./usage-indicator.ts";

const UNUSED: ContentUsage = {
  used: false,
  publication_count: 0,
  published_count: 0,
  awaiting_count: 0,
  scheduled_count: 0,
  platforms: [],
  last_published_at: null,
  draft_count: 0,
  attention_count: 0,
  upcoming_count: 0,
  next_scheduled_at: null,
  cancelled_count: 0,
};

function usage(values: Partial<ContentUsage>): ContentUsage {
  return { ...UNUSED, ...values };
}

describe("usageIndicator", () => {
  const now = new Date(2026, 9, 19, 9, 0);
  const tomorrow = new Date(2026, 9, 20, 18, 0).toISOString();

  it.each<[string, Partial<ContentUsage>, string | null]>([
    [
      "attention wins over everything",
      {
        publication_count: 4,
        attention_count: 2,
        upcoming_count: 1,
        draft_count: 1,
        published_count: 3,
      },
      "2 need attention",
    ],
    [
      "one needs attention",
      { publication_count: 1, attention_count: 1 },
      "1 needs attention",
    ],
    [
      "scheduled before drafts",
      {
        publication_count: 2,
        upcoming_count: 1,
        next_scheduled_at: tomorrow,
        draft_count: 1,
      },
      `Scheduled · ${"Tomorrow"}`,
    ],
    [
      "publishing without a date",
      { publication_count: 1, upcoming_count: 1 },
      "Publishing",
    ],
    [
      "drafts before published",
      { publication_count: 3, draft_count: 2, published_count: 1 },
      "2 drafts",
    ],
    ["published", { publication_count: 1, published_count: 1 }, "Published"],
    ["never used", {}, "Not used yet"],
    [
      "only cancelled posts",
      { publication_count: 2, cancelled_count: 2 },
      "Not used yet",
    ],
  ])("%s", (_label, values, expected) => {
    const label = usageIndicator(usage(values), now)?.label ?? null;
    if (expected?.startsWith("Scheduled")) {
      expect(label).toMatch(/^Scheduled · Tomorrow /);
    } else {
      expect(label).toBe(expected);
    }
  });
});

describe("filterMedia", () => {
  function media(id: number, values: Partial<Content>): Content {
    return {
      id,
      media_type: "image",
      original_filename: `file-${id}.png`,
      title: null,
      description: null,
      hashtags: [],
      usage: UNUSED,
      ...values,
    } as Content;
  }
  const contents = [
    media(1, { title: "Summer teaser", media_type: "video" }),
    media(2, { description: "Beach day", hashtags: ["holiday"] }),
    media(3, {
      original_filename: "SUMMER.jpg",
      usage: usage({ publication_count: 1, published_count: 1 }),
    }),
    media(4, { usage: usage({ publication_count: 1, cancelled_count: 1 }) }),
  ];

  it.each<[string, LibraryFilter, number[]]>([
    ["", "all", [1, 2, 3, 4]],
    ["summer", "all", [1, 3]],
    ["#holiday", "all", [2]],
    ["beach", "all", [2]],
    ["", "videos", [1]],
    ["", "images", [2, 3, 4]],
    ["", "unused", [1, 2, 4]],
    ["summer", "unused", [1]],
  ])("search %j with %s", (query, filter, ids) => {
    expect(filterMedia(contents, query, filter).map((item) => item.id)).toEqual(
      ids,
    );
  });
});
