import { useCallback, useMemo } from "react";
import { useLocation, useSearchParams } from "react-router";
import {
  clearFilters as withoutFilters,
  withoutFilter,
} from "./library-filters.ts";
import {
  type FilterKey,
  type LibraryQuery,
  parseLibraryQuery,
  serializeLibraryQuery,
} from "./library-query.ts";

/**
 * The only reader and writer of the Library query (research R1). Every write
 * replaces the history entry and keeps `location.state`; nothing rewrites the
 * URL on load, so invalid params stay until the next user change.
 */
export function useLibraryQuery() {
  const location = useLocation();
  const [, setParams] = useSearchParams();
  const query = useMemo(
    () => parseLibraryQuery(new URLSearchParams(location.search)),
    [location.search],
  );
  const search = serializeLibraryQuery(query);
  const state: unknown = location.state;

  const write = useCallback(
    (change: (current: LibraryQuery) => LibraryQuery) =>
      setParams(
        (current) =>
          new URLSearchParams(
            serializeLibraryQuery(change(parseLibraryQuery(current))),
          ),
        { replace: true, state },
      ),
    [setParams, state],
  );

  const update = useCallback(
    (patch: Partial<LibraryQuery>) =>
      write((current) => ({ ...current, ...patch })),
    [write],
  );
  const clearSearch = useCallback(
    () => write((current) => ({ ...current, q: "" })),
    [write],
  );
  const clearFilters = useCallback(() => write(withoutFilters), [write]);
  const removeFilter = useCallback(
    (key: FilterKey) => write((current) => withoutFilter(current, key)),
    [write],
  );

  return { query, search, update, clearSearch, clearFilters, removeFilter };
}
