import type { LibraryScope } from "../../api.ts";
import Button from "../../ui/Button.tsx";
import EmptyState from "../../ui/EmptyState.tsx";
import { emptyResultsKind, filterControlSelector } from "./library-filters.ts";
import { libraryViewPath } from "./library-folders.ts";
import { useLibraryQuery } from "./useLibraryQuery.ts";

/** The control that stays once this empty state goes (never the document). */
function focus(selector: string) {
  document.querySelector<HTMLElement>(selector)?.focus();
}

/**
 * A view with Media and no results for its query (contracts/ui.md §8): why,
 * and how to widen it. `Search all media` runs the same query over All media,
 * from a folder or Unsorted only.
 */
function EmptyResults({
  projectId,
  scope,
}: {
  projectId: number;
  scope: LibraryScope;
}) {
  const { query, search, clearSearch, clearFilters } = useLibraryQuery();
  const kind = emptyResultsKind(query);
  if (kind === null) {
    return null;
  }

  const clearSearchButton = (
    <Button
      variant="primary"
      onClick={() => {
        clearSearch();
        focus("input[type='search']");
      }}
    >
      Clear search
    </Button>
  );
  const clearFiltersButton = (
    <Button
      variant={kind === "filters" ? "primary" : "secondary"}
      onClick={() => {
        clearFilters();
        focus(filterControlSelector("type"));
      }}
    >
      Clear filters
    </Button>
  );
  const secondary =
    kind !== "filters" && scope.kind !== "all"
      ? {
          to: libraryViewPath(projectId, { kind: "all" }) + search,
          label: "Search all media",
        }
      : undefined;

  return (
    <EmptyState
      headingLevel={2}
      title={
        kind === "search"
          ? `No media match "${query.q.trim()}"`
          : kind === "filters"
            ? "No media match these filters"
            : "No media match the search and filters"
      }
      action={
        kind === "search" ? (
          clearSearchButton
        ) : kind === "filters" ? (
          clearFiltersButton
        ) : (
          <>
            {clearSearchButton}
            {clearFiltersButton}
          </>
        )
      }
      secondary={secondary}
    />
  );
}

export default EmptyResults;
