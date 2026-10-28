import type { Content } from "../../types.ts";
import {
  DEFAULT_LIBRARY_QUERY,
  type FilterKey,
  type ImportedFilter,
  type LibraryQuery,
  type LibrarySort,
  type TypeFilter,
  type UsageFilter,
} from "./library-query.ts";
import { usageOf } from "./usage-indicator.ts";

// --- Search (research R3) ---

/** Without diacritics and lowercased: `Café` → `cafe`, `NIÑO` → `nino`. */
export function normalizeText(value: string): string {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Normalized words, without leading `#`; empty tokens are dropped. */
export function tokenize(query: string): string[] {
  return normalizeText(query)
    .split(/\s+/)
    .map((token) => token.replace(/^#+/, ""))
    .filter(Boolean);
}

/**
 * The searchable text of a Media: its fields normalized and joined with a line
 * break. Tokens never contain whitespace, so one never matches across fields.
 */
export function searchText(content: Content): string {
  return [
    content.title ?? "",
    content.original_filename,
    content.description ?? "",
    ...content.hashtags,
  ]
    .map(normalizeText)
    .join("\n");
}

/** The searchable text of every Media, by id; memoize it on the list. */
export function searchIndex(contents: readonly Content[]): Map<number, string> {
  return new Map(contents.map((content) => [content.id, searchText(content)]));
}

/** Every token is a literal substring of the text (never a regex). */
export function matchesTokens(
  text: string,
  tokens: readonly string[],
): boolean {
  return tokens.every((token) => text.includes(token));
}

// --- Filters (research R4, R5, R14, R16) ---

const DAY_MS = 86_400_000;
const IMPORTED_DAYS: Record<Exclude<ImportedFilter, "any">, number> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
};

/** Imported at most `days` × 24 h before `now` (ms), inclusive. */
export function importedWithin(
  content: Content,
  days: number,
  now: number,
): boolean {
  return Date.parse(content.created_at) >= now - days * DAY_MS;
}

interface FilterDimension<K extends FilterKey, V extends string> {
  key: K;
  label: string;
  /** The first option is the default. */
  options: ReadonlyArray<{ value: V; label: string }>;
}

/** The one table of the filter dimensions, in chip order. */
export const FILTER_DIMENSIONS: readonly [
  FilterDimension<"type", TypeFilter>,
  FilterDimension<"usage", UsageFilter>,
  FilterDimension<"imported", ImportedFilter>,
] = [
  {
    key: "type",
    label: "Type",
    options: [
      { value: "all", label: "All" },
      { value: "images", label: "Images" },
      { value: "videos", label: "Videos" },
    ],
  },
  {
    key: "usage",
    label: "Usage",
    options: [
      { value: "all", label: "All" },
      { value: "used", label: "Used" },
      { value: "unused", label: "Unused" },
    ],
  },
  {
    key: "imported",
    label: "Imported",
    options: [
      { value: "any", label: "Any time" },
      { value: "7d", label: "Last 7 days" },
      { value: "30d", label: "Last 30 days" },
      { value: "90d", label: "Last 90 days" },
    ],
  },
];

export const SORT_OPTIONS: ReadonlyArray<{
  value: LibrarySort;
  label: string;
}> = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "name-asc", label: "Name A–Z" },
  { value: "name-desc", label: "Name Z–A" },
];

export interface ActiveFilter {
  key: FilterKey;
  /** The value's label: "Videos", "Unused", "Last 30 days". */
  label: string;
}

/** One chip per non-default dimension, in Type, Usage, Imported order. */
export function activeFilters(query: LibraryQuery): ActiveFilter[] {
  return FILTER_DIMENSIONS.flatMap((dimension) => {
    const value = query[dimension.key];
    if (value === DEFAULT_LIBRARY_QUERY[dimension.key]) {
      return [];
    }
    const option = dimension.options.find((item) => item.value === value);
    return [{ key: dimension.key, label: option?.label ?? value }];
  });
}

export function hasActiveFilters(query: LibraryQuery): boolean {
  return activeFilters(query).length > 0;
}

/** Resets one dimension only. */
export function withoutFilter(
  query: LibraryQuery,
  key: FilterKey,
): LibraryQuery {
  return { ...query, [key]: DEFAULT_LIBRARY_QUERY[key] };
}

/** Resets Type, Usage and Imported; keeps `q` and `sort`. */
export function clearFilters(query: LibraryQuery): LibraryQuery {
  return {
    ...query,
    type: DEFAULT_LIBRARY_QUERY.type,
    usage: DEFAULT_LIBRARY_QUERY.usage,
    imported: DEFAULT_LIBRARY_QUERY.imported,
  };
}

export type EmptyResultsKind = "search" | "filters" | "both";

/** Why a view with Media shows no results; null when nothing narrows it. */
export function emptyResultsKind(query: LibraryQuery): EmptyResultsKind | null {
  const searching = tokenize(query.q).length > 0;
  const filtering = hasActiveFilters(query);
  if (searching && filtering) {
    return "both";
  }
  if (searching) {
    return "search";
  }
  return filtering ? "filters" : null;
}

/**
 * The visible control of a filter dimension: its select from md up, or the
 * `Filters` button below (only one layout is mounted).
 */
export function filterControlSelector(key: FilterKey): string {
  return `[data-filter-select="${key}"], [data-filters-button]`;
}

// --- Sort (research R6) ---

const collator = new Intl.Collator(undefined, {
  sensitivity: "base",
  numeric: true,
});

type Comparator = (a: Content, b: Content) => number;

/** `created_at` desc, then `id` desc: the backend's list order. */
const newest: Comparator = (a, b) =>
  Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id;

function displayName(content: Content): string {
  return content.title ?? content.original_filename;
}

const COMPARATORS: Record<LibrarySort, Comparator> = {
  newest,
  oldest: (a, b) => newest(b, a),
  "name-asc": (a, b) =>
    collator.compare(displayName(a), displayName(b)) || newest(a, b),
  "name-desc": (a, b) =>
    collator.compare(displayName(b), displayName(a)) || newest(a, b),
};

/** A sorted copy; the input is never mutated. */
export function sortMedia(
  list: readonly Content[],
  sort: LibrarySort,
): Content[] {
  return [...list].sort(COMPARATORS[sort]);
}

// --- Pipeline (research R7) ---

export interface LibraryResults {
  results: Content[];
  visibleIds: ReadonlySet<number>;
}

/**
 * The view's Media that match type AND usage AND imported AND search, sorted.
 * `contents` is the view's universe as loaded; `now` is in ms; `index` is an
 * optional precomputed `searchIndex(contents)`.
 */
export function libraryResults(
  contents: readonly Content[],
  query: LibraryQuery,
  now: number,
  index?: ReadonlyMap<number, string>,
): LibraryResults {
  const tokens = tokenize(query.q);
  const days = query.imported === "any" ? null : IMPORTED_DAYS[query.imported];
  const filtered = contents.filter(
    (content) =>
      (query.type === "all" ||
        content.media_type === (query.type === "images" ? "image" : "video")) &&
      (query.usage === "all" || usageOf(content) === query.usage) &&
      (days === null || importedWithin(content, days, now)) &&
      (tokens.length === 0 ||
        matchesTokens(index?.get(content.id) ?? searchText(content), tokens)),
  );
  const results = sortMedia(filtered, query.sort);
  return {
    results,
    visibleIds: new Set(results.map((content) => content.id)),
  };
}
