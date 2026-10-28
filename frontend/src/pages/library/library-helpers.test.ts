import { describe, expect, it } from "vitest";
import type { Content, ContentUsage } from "../../types.ts";
import {
  activeFilters,
  clearFilters,
  emptyResultsKind,
  hasActiveFilters,
  importedWithin,
  libraryResults,
  normalizeText,
  searchIndex,
  sortMedia,
  tokenize,
  withoutFilter,
} from "./library-filters.ts";
import {
  DEFAULT_LIBRARY_QUERY,
  IMPORTED_VALUES,
  type LibraryQuery,
  type LibrarySort,
  TYPE_VALUES,
  USAGE_VALUES,
} from "./library-query.ts";
import { isNotUsedYet, usageIndicator, usageOf } from "./usage-indicator.ts";

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

  // Same tones as the status map (contracts/ui.md §5).
  it.each<[string, Partial<ContentUsage>, string]>([
    ["attention", { publication_count: 1, attention_count: 1 }, "warning"],
    [
      "scheduled",
      {
        publication_count: 1,
        upcoming_count: 1,
        next_scheduled_at: tomorrow,
      },
      "neutral",
    ],
    ["publishing", { publication_count: 1, upcoming_count: 1 }, "active"],
    ["drafts", { publication_count: 1, draft_count: 1 }, "neutral"],
    ["published", { publication_count: 1, published_count: 1 }, "success"],
    ["not used yet", {}, "neutral"],
  ])("%s tone", (_label, values, tone) => {
    expect(usageIndicator(usage(values), now)?.tone).toBe(tone);
  });
});

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-28T12:00:00Z");

function media(id: number, values: Partial<Content> = {}): Content {
  return {
    id,
    media_type: "image",
    original_filename: `file-${id}.png`,
    title: null,
    description: null,
    hashtags: [],
    usage: UNUSED,
    created_at: new Date(NOW - id * DAY).toISOString(),
    ...values,
  } as Content;
}

function query(values: Partial<LibraryQuery> = {}): LibraryQuery {
  return { ...DEFAULT_LIBRARY_QUERY, ...values };
}

function ids(list: readonly Content[]): number[] {
  return list.map((item) => item.id);
}

describe("search", () => {
  it.each([
    ["Café", "cafe"],
    ["NIÑO", "nino"],
    ["Ação", "acao"],
  ])("normalizeText(%j) is %j", (value, expected) => {
    expect(normalizeText(value)).toBe(expected);
  });

  it.each<[string, string[]]>([
    ["  #  ##summer  ", ["summer"]],
    ["Café  #Verano", ["cafe", "verano"]],
    ["   ", []],
    ["", []],
  ])("tokenize(%j)", (value, expected) => {
    expect(tokenize(value)).toEqual(expected);
  });

  const contents = [
    media(1, { title: "Café de verano", media_type: "video" }),
    media(2, { description: "Beach day", hashtags: ["Holiday"] }),
    media(3, { original_filename: "IMG_2045.jpg" }),
    media(4, { title: "Summer", description: "time" }),
    media(5, { title: "Plan a.b 50% (1) 🌞" }),
    media(6, { title: "axb" }),
  ];

  it.each<[string, number[]]>([
    ["", [1, 2, 3, 4, 5, 6]],
    ["   ", [1, 2, 3, 4, 5, 6]],
    ["CAFE VERANO", [1]],
    ["verano café", [1]],
    ["cafe invierno", []],
    // Tokens may sit in different fields (title + description)…
    ["summer time", [4]],
    // …but one token never spans two fields.
    ["summertime", []],
    ["#holiday", [2]],
    ["##HOLIDAY beach", [2]],
    ["img_2045", [3]],
    ["2045.jpg", [3]],
    ["file-1", [1]],
    ["a.b", [5]],
    ["50%", [5]],
    ["(1)", [5]],
    ["🌞", [5]],
  ])("q=%j matches %j", (q, expected) => {
    expect(ids(libraryResults(contents, query({ q }), NOW).results)).toEqual(
      expected,
    );
  });

  it("gives the same results with a precomputed index", () => {
    const index = searchIndex(contents);
    for (const q of ["cafe", "summer time", "holiday", "nothing"]) {
      expect(libraryResults(contents, query({ q }), NOW, index)).toEqual(
        libraryResults(contents, query({ q }), NOW),
      );
    }
  });
});

describe("usage", () => {
  it.each<[string, Partial<ContentUsage>, "used" | "unused"]>([
    ["no Posts", {}, "unused"],
    ["only cancelled", { publication_count: 2, cancelled_count: 2 }, "unused"],
    ["a draft", { publication_count: 1, draft_count: 1 }, "used"],
    ["scheduled", { publication_count: 1, upcoming_count: 1 }, "used"],
    ["failed", { publication_count: 1, attention_count: 1 }, "used"],
    ["published", { publication_count: 1, published_count: 1 }, "used"],
    [
      "awaiting user action",
      { publication_count: 1, awaiting_count: 1 },
      "used",
    ],
    [
      "cancelled plus one draft on another account",
      { publication_count: 3, cancelled_count: 2, draft_count: 1 },
      "used",
    ],
    // `used` is the backend's published/awaiting flag: never read.
    ["ignores usage.used", { used: true }, "unused"],
  ])("%s → %s", (_label, values, expected) => {
    const item = { usage: usage(values) };
    expect(usageOf(item)).toBe(expected);
    expect(isNotUsedYet(item.usage)).toBe(expected === "unused");
  });

  it("partitions every Media into Used or Unused", () => {
    const contents = [
      media(1),
      media(2, { usage: usage({ publication_count: 1, cancelled_count: 1 }) }),
      media(3, { usage: usage({ publication_count: 2, draft_count: 2 }) }),
      media(4, { usage: usage({ publication_count: 1, published_count: 1 }) }),
    ];
    const used = ids(
      libraryResults(contents, query({ usage: "used" }), NOW).results,
    );
    const unused = ids(
      libraryResults(contents, query({ usage: "unused" }), NOW).results,
    );
    expect(used).toEqual([3, 4]);
    expect(unused).toEqual([1, 2]);
  });
});

describe("importedWithin", () => {
  it.each([7, 30, 90])("%i days: inclusive limit", (days) => {
    const at = (ms: number) =>
      media(1, { created_at: new Date(ms).toISOString() });
    expect(importedWithin(at(NOW - days * DAY + 1), days, NOW)).toBe(true);
    expect(importedWithin(at(NOW - days * DAY), days, NOW)).toBe(true);
    expect(importedWithin(at(NOW - days * DAY - 1), days, NOW)).toBe(false);
    expect(importedWithin(at(NOW + DAY), days, NOW)).toBe(true);
  });
});

describe("filter combinations", () => {
  // Every type × usage × age, with the expected answer kept in the fixture.
  const AGES = [1, 10, 45, 100];
  const fixture: Array<{
    content: Content;
    type: "images" | "videos";
    used: boolean;
    age: number;
  }> = [];
  for (const type of ["images", "videos"] as const) {
    for (const used of [false, true]) {
      for (const age of AGES) {
        const id = fixture.length + 1;
        fixture.push({
          type,
          used,
          age,
          content: media(id, {
            media_type: type === "images" ? "image" : "video",
            created_at: new Date(NOW - age * DAY).toISOString(),
            usage: used
              ? usage({
                  publication_count: 2,
                  cancelled_count: 1,
                  draft_count: 1,
                })
              : usage({ publication_count: 1, cancelled_count: 1 }),
          }),
        });
      }
    }
  }
  const contents = fixture.map((item) => item.content);
  const MAX_AGE = { any: Infinity, "7d": 7, "30d": 30, "90d": 90 };

  const combinations = TYPE_VALUES.flatMap((type) =>
    USAGE_VALUES.flatMap((usageValue) =>
      IMPORTED_VALUES.map((imported) => ({
        type,
        usage: usageValue,
        imported,
      })),
    ),
  );

  it("covers 36 combinations", () => {
    expect(combinations).toHaveLength(36);
  });

  it.each(combinations)(
    "type=$type usage=$usage imported=$imported",
    (filters) => {
      const expected = fixture
        .filter(
          (item) =>
            (filters.type === "all" || item.type === filters.type) &&
            (filters.usage === "all" ||
              item.used === (filters.usage === "used")) &&
            item.age <= MAX_AGE[filters.imported],
        )
        .map((item) => item.content.id)
        .sort((a, b) => a - b);
      const actual = ids(libraryResults(contents, query(filters), NOW).results);
      expect([...actual].sort((a, b) => a - b)).toEqual(expected);
    },
  );
});

describe("sortMedia", () => {
  const at = (iso: string) => ({ created_at: iso });
  const contents = [
    media(1, { title: "a10", ...at("2026-10-01T10:00:00Z") }),
    media(2, { title: "Á2", ...at("2026-10-03T10:00:00Z") }),
    media(3, { original_filename: "b1.png", ...at("2026-10-02T10:00:00Z") }),
    // Same instant as 2: the higher id is newer.
    media(4, { title: "Same", ...at("2026-10-03T10:00:00Z") }),
    media(5, { title: "same", ...at("2026-10-03T10:00:00Z") }),
    media(6, { title: "SAME", ...at("2026-09-01T10:00:00Z") }),
  ];

  it.each<[LibrarySort, number[]]>([
    ["newest", [5, 4, 2, 3, 1, 6]],
    ["oldest", [6, 1, 3, 2, 4, 5]],
    ["name-asc", [2, 1, 3, 5, 4, 6]],
    ["name-desc", [5, 4, 6, 3, 1, 2]],
  ])("%s", (sort, expected) => {
    expect(ids(sortMedia(contents, sort))).toEqual(expected);
  });

  it("does not mutate the input", () => {
    const before = ids(contents);
    sortMedia(contents, "name-desc");
    expect(ids(contents)).toEqual(before);
  });
});

describe("pipeline and chips", () => {
  const contents = [
    media(1, { title: "Summer video", media_type: "video" }),
    media(2, { title: "Summer photo" }),
    media(3, {
      title: "Summer clip",
      media_type: "video",
      usage: usage({ publication_count: 1, published_count: 1 }),
    }),
    media(40, { title: "Old summer video", media_type: "video" }),
  ];

  it("combines search AND type AND usage AND imported, then sorts", () => {
    const { results, visibleIds } = libraryResults(
      contents,
      query({
        q: "summer",
        type: "videos",
        usage: "unused",
        imported: "30d",
        sort: "oldest",
      }),
      NOW,
    );
    expect(ids(results)).toEqual([1]);
    expect([...visibleIds]).toEqual([1]);
    expect(
      ids(
        libraryResults(contents, query({ q: "summer", type: "videos" }), NOW)
          .results,
      ),
    ).toEqual([1, 3, 40]);
  });

  it("changing only the sort never changes the set", () => {
    const sets = (["newest", "oldest", "name-asc", "name-desc"] as const).map(
      (sort) =>
        [
          ...libraryResults(contents, query({ q: "summer", sort }), NOW)
            .visibleIds,
        ].sort((a, b) => a - b),
    );
    expect(new Set(sets.map(String)).size).toBe(1);
  });

  it("lists active filters in Type, Usage, Imported order", () => {
    const value = query({ imported: "30d", usage: "unused", type: "videos" });
    expect(activeFilters(value)).toEqual([
      { key: "type", label: "Videos" },
      { key: "usage", label: "Unused" },
      { key: "imported", label: "Last 30 days" },
    ]);
    expect(activeFilters(query({ q: "x", sort: "oldest" }))).toEqual([]);
  });

  it("removes one filter or all of them", () => {
    const value = query({
      q: "cafe",
      type: "images",
      usage: "used",
      imported: "7d",
      sort: "name-asc",
    });
    expect(withoutFilter(value, "usage")).toEqual({ ...value, usage: "all" });
    expect(clearFilters(value)).toEqual(query({ q: "cafe", sort: "name-asc" }));
    expect(hasActiveFilters(value)).toBe(true);
    expect(hasActiveFilters(clearFilters(value))).toBe(false);
  });

  it.each<[Partial<LibraryQuery>, ReturnType<typeof emptyResultsKind>]>([
    [{ q: "cafe" }, "search"],
    [{ usage: "used" }, "filters"],
    [{ q: "cafe", imported: "7d" }, "both"],
    [{ q: " # ", sort: "oldest" }, null],
  ])("emptyResultsKind(%j) is %j", (values, expected) => {
    expect(emptyResultsKind(query(values))).toBe(expected);
  });
});
