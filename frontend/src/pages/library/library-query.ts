import type { LibraryScope } from "../../api.ts";

export const TYPE_VALUES = ["all", "images", "videos"] as const;
export const USAGE_VALUES = ["all", "used", "unused"] as const;
export const IMPORTED_VALUES = ["any", "7d", "30d", "90d"] as const;
export const SORT_VALUES = [
  "newest",
  "oldest",
  "name-asc",
  "name-desc",
] as const;

export type TypeFilter = (typeof TYPE_VALUES)[number];
export type UsageFilter = (typeof USAGE_VALUES)[number];
export type ImportedFilter = (typeof IMPORTED_VALUES)[number];
export type LibrarySort = (typeof SORT_VALUES)[number];

/** The Library search, filters and sort; the URL is its only source. */
export interface LibraryQuery {
  /** What the user typed, untouched; normalization only applies to matching. */
  q: string;
  type: TypeFilter;
  usage: UsageFilter;
  imported: ImportedFilter;
  sort: LibrarySort;
}

/** The filter dimensions: chips, Clear all and the selection key cover these. */
export type FilterKey = "type" | "usage" | "imported";

export const DEFAULT_LIBRARY_QUERY: LibraryQuery = {
  q: "",
  type: "all",
  usage: "all",
  imported: "any",
  sort: "newest",
};

function oneOf<T extends string>(
  values: readonly T[],
  value: string | null,
  fallback: T,
): T {
  return values.find((candidate) => candidate === value) ?? fallback;
}

/** Unknown or invalid values fall back to the default; repeats use the first. */
export function parseLibraryQuery(params: URLSearchParams): LibraryQuery {
  return {
    q: params.get("q") ?? "",
    type: oneOf(TYPE_VALUES, params.get("type"), "all"),
    usage: oneOf(USAGE_VALUES, params.get("usage"), "all"),
    imported: oneOf(IMPORTED_VALUES, params.get("imported"), "any"),
    sort: oneOf(SORT_VALUES, params.get("sort"), "newest"),
  };
}

/**
 * `""` or `"?…"`, in the fixed order q, type, usage, imported, sort. Defaults
 * and a blank `q` are omitted (contracts/ui.md §1).
 */
export function serializeLibraryQuery(query: LibraryQuery): string {
  const params = new URLSearchParams();
  if (query.q.trim() !== "") {
    params.set("q", query.q);
  }
  for (const key of ["type", "usage", "imported", "sort"] as const) {
    if (query[key] !== DEFAULT_LIBRARY_QUERY[key]) {
      params.set(key, query[key]);
    }
  }
  const search = params.toString();
  return search === "" ? "" : `?${search}`;
}

/** What a selection belongs to: everything but the sort (research R8). */
export function selectionKey(query: LibraryQuery): string {
  return serializeLibraryQuery({ ...query, sort: DEFAULT_LIBRARY_QUERY.sort });
}

export interface LibraryReturn {
  scope: LibraryScope;
  query: LibraryQuery;
}

/**
 * Publish's `from` value: the view relative to `/p/:projectId/library/` plus
 * the serialized query, e.g. `folders/12?q=cafe`. Not URL-encoded: callers put
 * it in a `URLSearchParams` (or `encodeURIComponent`) like any other value.
 */
export function libraryReturnParam(
  scope: LibraryScope,
  query: LibraryQuery,
): string {
  const view =
    scope.kind === "folder" ? `folders/${scope.folderId}` : scope.kind;
  return view + serializeLibraryQuery(query);
}

const RETURN_GRAMMAR = /^(all|unsorted|folders\/([1-9]\d{0,9}))(?:\?(.*))?$/;
const MAX_ID = 2_147_483_647;

/**
 * The view and query of a `from` value, or null. Only `all`, `unsorted` and
 * `folders/<positive id>` are accepted; the query is re-parsed, so unknown
 * params are dropped. Callers rebuild the destination from the result and
 * never navigate to the raw value (research R10).
 */
export function parseLibraryReturn(
  value: string | null | undefined,
): LibraryReturn | null {
  const match = RETURN_GRAMMAR.exec(value ?? "");
  if (match === null) {
    return null;
  }
  const [, view, folderId, search = ""] = match;
  let scope: LibraryScope;
  if (folderId !== undefined) {
    const id = Number(folderId);
    if (id > MAX_ID) {
      return null;
    }
    scope = { kind: "folder", folderId: id };
  } else {
    scope = { kind: view as "all" | "unsorted" };
  }
  return { scope, query: parseLibraryQuery(new URLSearchParams(search)) };
}
