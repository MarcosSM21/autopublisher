import Button from "../../ui/Button.tsx";
import ChoiceGroup from "../../ui/ChoiceGroup.tsx";
import { LIBRARY_FILTERS, type LibraryFilter } from "./library-filters.ts";

interface LibraryToolbarProps {
  /** Count, import, search and filters; off for an empty Library. */
  showTools: boolean;
  count: number;
  query: string;
  onQueryChange: (query: string) => void;
  filter: LibraryFilter;
  onFilterChange: (filter: LibraryFilter) => void;
  /** Whether importing is the page's next step (see onboarding). */
  importPrimary: boolean;
  importDisabledReason: string | null;
  /** An import is running: a second one waits. */
  importBusy: boolean;
  onImport: () => void;
}

/**
 * Library header: title, count, Import media, then search and filters. The
 * title is always there (the same element while the list loads).
 */
function LibraryToolbar({
  showTools,
  count,
  query,
  onQueryChange,
  filter,
  onFilterChange,
  importPrimary,
  importDisabledReason,
  importBusy,
  onImport,
}: LibraryToolbarProps) {
  return (
    <div className="ap-library__toolbar">
      <div className="ap-library__header">
        <h1 className="ap-page-title">Library</h1>
        {showTools && (
          <>
            <span className="ap-meta">{count} media</span>
            <Button
              className="ap-library__import"
              variant={importPrimary ? "primary" : "secondary"}
              icon="plus"
              disabled={importDisabledReason !== null || importBusy}
              onClick={onImport}
            >
              Import media
            </Button>
          </>
        )}
      </div>
      {showTools && importDisabledReason && (
        <p className="ap-meta">{importDisabledReason}</p>
      )}
      {showTools && (
        <div className="ap-library__filters">
          <input
            type="search"
            className="ap-library__search"
            aria-label="Search media"
            placeholder="Search title, file name, caption or #hashtag"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
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
            onChange={onFilterChange}
          />
        </div>
      )}
    </div>
  );
}

export default LibraryToolbar;
