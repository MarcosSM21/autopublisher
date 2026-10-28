import { describe, expect, it } from "vitest";
import {
  DEFAULT_LIBRARY_QUERY,
  type LibraryQuery,
  libraryReturnParam,
  parseLibraryQuery,
  parseLibraryReturn,
  selectionKey,
  serializeLibraryQuery,
} from "./library-query.ts";

function parse(search: string): LibraryQuery {
  return parseLibraryQuery(new URLSearchParams(search));
}

const FULL: LibraryQuery = {
  q: "Café #verano",
  type: "videos",
  usage: "unused",
  imported: "30d",
  sort: "name-asc",
};

describe("parseLibraryQuery", () => {
  it("defaults to every value's default", () => {
    expect(parse("")).toEqual(DEFAULT_LIBRARY_QUERY);
  });

  it("reads valid values and keeps q as typed", () => {
    expect(
      parse(
        "?q=Caf%C3%A9+%23verano&type=videos&usage=unused&imported=30d&sort=name-asc",
      ),
    ).toEqual(FULL);
    expect(parse("?type=images&usage=used&imported=7d&sort=oldest")).toEqual({
      ...DEFAULT_LIBRARY_QUERY,
      type: "images",
      usage: "used",
      imported: "7d",
      sort: "oldest",
    });
  });

  it("falls back to the default for invalid values", () => {
    expect(
      parse("?type=gif&usage=maybe&imported=365&sort=size&posts=1"),
    ).toEqual(DEFAULT_LIBRARY_QUERY);
    expect(parse("?type=VIDEOS&imported=7")).toEqual(DEFAULT_LIBRARY_QUERY);
  });

  it("uses the first of repeated params", () => {
    expect(parse("?type=videos&type=images&q=a&q=b")).toEqual({
      ...DEFAULT_LIBRARY_QUERY,
      q: "a",
      type: "videos",
    });
  });
});

describe("serializeLibraryQuery", () => {
  it("omits defaults and a blank q", () => {
    expect(serializeLibraryQuery(DEFAULT_LIBRARY_QUERY)).toBe("");
    expect(serializeLibraryQuery({ ...DEFAULT_LIBRARY_QUERY, q: "   " })).toBe(
      "",
    );
    expect(
      serializeLibraryQuery({ ...DEFAULT_LIBRARY_QUERY, sort: "oldest" }),
    ).toBe("?sort=oldest");
  });

  it("writes keys in a fixed order", () => {
    const shuffled: LibraryQuery = {
      sort: "name-desc",
      imported: "90d",
      usage: "used",
      type: "images",
      q: "cafe verano",
    };
    expect(serializeLibraryQuery(shuffled)).toBe(
      "?q=cafe+verano&type=images&usage=used&imported=90d&sort=name-desc",
    );
  });

  it("round-trips", () => {
    for (const query of [
      DEFAULT_LIBRARY_QUERY,
      FULL,
      { ...FULL, q: "50% & a=b ?#" },
    ]) {
      expect(parse(serializeLibraryQuery(query))).toEqual(query);
    }
  });
});

describe("selectionKey", () => {
  it("ignores the sort", () => {
    expect(selectionKey({ ...FULL, sort: "oldest" })).toBe(selectionKey(FULL));
  });

  it.each<Partial<LibraryQuery>>([
    { q: "other" },
    { type: "images" },
    { usage: "used" },
    { imported: "7d" },
  ])("changes with %j", (change) => {
    expect(selectionKey({ ...FULL, ...change })).not.toBe(selectionKey(FULL));
  });
});

describe("Publish return", () => {
  it.each([
    [{ kind: "all" } as const, DEFAULT_LIBRARY_QUERY, "all"],
    [
      { kind: "unsorted" } as const,
      { ...DEFAULT_LIBRARY_QUERY, sort: "oldest" } as const,
      "unsorted?sort=oldest",
    ],
    [
      { kind: "folder", folderId: 12 } as const,
      { ...DEFAULT_LIBRARY_QUERY, q: "cafe", type: "videos" } as const,
      "folders/12?q=cafe&type=videos",
    ],
  ])("libraryReturnParam(%j)", (scope, query, expected) => {
    const value = libraryReturnParam(scope, query);
    expect(value).toBe(expected);
    expect(parseLibraryReturn(value)).toEqual({ scope, query });
  });

  it("survives encoding as a URL param", () => {
    const value = libraryReturnParam({ kind: "folder", folderId: 7 }, FULL);
    const params = new URLSearchParams({ posts: "1,2", from: value });
    expect(
      parseLibraryReturn(new URLSearchParams(params.toString()).get("from")),
    ).toEqual({ scope: { kind: "folder", folderId: 7 }, query: FULL });
  });

  it("re-parses the query and drops unknown params", () => {
    expect(parseLibraryReturn("all?q=x&type=gif&evil=1&sort=oldest")).toEqual({
      scope: { kind: "all" },
      query: { ...DEFAULT_LIBRARY_QUERY, q: "x", sort: "oldest" },
    });
  });

  it.each([
    "",
    null,
    undefined,
    "//evil.com",
    "https://x",
    "/p/2/library/all",
    "../",
    "all/../../x",
    "folders/0",
    "folders/-1",
    "folders/abc",
    "folders/12/34",
    "folders/012",
    "folders/99999999999",
    "folders/2147483648",
    "posts",
    "javascript:alert(1)",
    encodeURIComponent("javascript:alert(1)"),
    encodeURIComponent("all?q=x"),
    " all",
    "all\n?q=x",
  ])("rejects %j", (value) => {
    expect(parseLibraryReturn(value)).toBeNull();
  });
});
