import type { ReactNode } from "react";
import Button from "../../ui/Button.tsx";
import ChoiceGroup from "../../ui/ChoiceGroup.tsx";
import { LIBRARY_FILTERS, type LibraryFilter } from "./library-filters.ts";

interface LibraryToolbarProps {
  /** The view's h1: "Library", "Unsorted", "All media" or the folder name. */
  title: string;
  /** The view's Media count; null hides it. */
  count: number | null;
  /** Import media; off where the empty Library's drop zone offers it. */
  showImport: boolean;
  /** Search and filters; off while there is nothing to search. */
  showSearch: boolean;
  query?: string;
  onQueryChange?: (query: string) => void;
  filter?: LibraryFilter;
  onFilterChange?: (filter: LibraryFilter) => void;
  /** Whether importing is the page's next step (see onboarding). */
  importPrimary: boolean;
  importDisabledReason: string | null;
  /** An import is running: a second one waits. */
  importBusy: boolean;
  onImport: () => void;
  /** Enters Select mode; absent hides the button. */
  onSelect?: () => void;
  /** The view's other actions (New folder, the folder's More menu). */
  actions?: ReactNode;
}

/**
 * Library header: title, count, Import media and the view's actions, then
 * search and filters. The title is always there (the same element while the
 * list loads).
 */
function LibraryToolbar({
  title,
  count,
  showImport,
  showSearch,
  query = "",
  onQueryChange,
  filter = "all",
  onFilterChange,
  importPrimary,
  importDisabledReason,
  importBusy,
  onImport,
  onSelect,
  actions,
}: LibraryToolbarProps) {
  return (
    <div className="ap-library__toolbar">
      <div className="ap-page-header ap-library__header">
        <h1 className="ap-page-title">{title}</h1>
        {count !== null && <span className="ap-meta">{count} media</span>}
        <div className="ap-page-header__actions ap-library__actions">
          {showImport && (
            <Button
              variant={importPrimary ? "primary" : "secondary"}
              icon="plus"
              disabled={importDisabledReason !== null || importBusy}
              onClick={onImport}
            >
              Import media
            </Button>
          )}
          {onSelect && <Button onClick={onSelect}>Select</Button>}
          {actions}
        </div>
      </div>
      {showImport && importDisabledReason && (
        <p className="ap-meta">{importDisabledReason}</p>
      )}
      {showSearch && (
        <div className="ap-library__filters">
          <input
            type="search"
            className="ap-input ap-library__search"
            aria-label="Search media"
            placeholder="Search title, file name, caption or #hashtag"
            value={query}
            onChange={(event) => onQueryChange?.(event.target.value)}
          />
          <ChoiceGroup
            legend="Show"
            hideLegend
            orientation="horizontal"
            choices={LIBRARY_FILTERS.map(({ value, label }) => ({
              value,
              label,
            }))}
            value={filter}
            onChange={(value) => onFilterChange?.(value)}
          />
        </div>
      )}
    </div>
  );
}

export default LibraryToolbar;
