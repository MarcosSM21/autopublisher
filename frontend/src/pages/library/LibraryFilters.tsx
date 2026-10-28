import { useEffect, useRef } from "react";
import Button from "../../ui/Button.tsx";
import Field from "../../ui/Field.tsx";
import Icon from "../../ui/Icon.tsx";
import {
  activeFilters,
  emptyResultsKind,
  FILTER_DIMENSIONS,
  SORT_OPTIONS,
} from "./library-filters.ts";
import type { FilterKey, LibraryQuery, LibrarySort } from "./library-query.ts";
import { useLibraryQuery } from "./useLibraryQuery.ts";

/** Where focus goes once the URL change of a chip action is rendered. */
type PendingFocus =
  { kind: "chip"; key: FilterKey } | { kind: "select"; key: FilterKey };

/**
 * The Library's search, filters and sort (contracts/ui.md §3–§4, §9), read
 * from and written to the URL through `useLibraryQuery`. `resultCount` is the
 * number of Media the view shows for the current query.
 */
function LibraryFilters({ resultCount }: { resultCount: number }) {
  const { query, search, update, clearSearch, clearFilters, removeFilter } =
    useLibraryQuery();
  const chips = activeFilters(query);
  const root = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<PendingFocus | null>(null);

  useEffect(() => {
    const pending = pendingFocus.current;
    pendingFocus.current = null;
    if (pending === null) {
      return;
    }
    const selector =
      pending.kind === "chip"
        ? `[data-filter-chip="${pending.key}"]`
        : `[data-filter-select="${pending.key}"]`;
    root.current?.querySelector<HTMLElement>(selector)?.focus();
  }, [search]);

  function removeChip(key: FilterKey) {
    const index = chips.findIndex((chip) => chip.key === key);
    const neighbour = chips[index + 1] ?? chips[index - 1];
    pendingFocus.current = neighbour
      ? { kind: "chip", key: neighbour.key }
      : { kind: "select", key };
    removeFilter(key);
  }

  function clearAll() {
    pendingFocus.current = { kind: "select", key: "type" };
    clearFilters();
  }

  // Empty without search or filters; only the number, so sorting is silent.
  const narrowed = emptyResultsKind(query) !== null;
  const status = !narrowed
    ? ""
    : resultCount === 0
      ? "No media"
      : `${resultCount} media`;

  return (
    <div className="ap-library__query" ref={root}>
      <div className="ap-library__filters">
        <div className="ap-library__search">
          <input
            type="search"
            className="ap-input"
            aria-label="Search media"
            placeholder="Search title, file name, caption or #hashtag"
            value={query.q}
            onChange={(event) => update({ q: event.target.value })}
          />
          {query.q !== "" && (
            <Button variant="ghost" onClick={clearSearch}>
              Clear search
            </Button>
          )}
        </div>
        {FILTER_DIMENSIONS.map((dimension) => (
          <Field
            key={dimension.key}
            label={dimension.label}
            className="ap-library__select"
          >
            {(control) => (
              <select
                {...control}
                data-filter-select={dimension.key}
                value={query[dimension.key]}
                onChange={(event) =>
                  // The options are the dimension's values; parsing drops others.
                  update({
                    [dimension.key]: event.target.value,
                  } as Partial<LibraryQuery>)
                }
              >
                {dimension.options.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ))}
        <Field label="Sort" className="ap-library__select">
          {(control) => (
            <select
              {...control}
              value={query.sort}
              onChange={(event) =>
                update({ sort: event.target.value as LibrarySort })
              }
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
      {chips.length > 0 && (
        <div
          role="group"
          aria-label="Active filters"
          className="ap-library__chips"
        >
          {chips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              className="ap-button ap-button--secondary ap-library__chip"
              data-filter-chip={chip.key}
              aria-label={`Remove filter: ${chip.label}`}
              onClick={() => removeChip(chip.key)}
            >
              <span>{chip.label}</span>
              <Icon name="close" />
            </button>
          ))}
          <Button variant="ghost" onClick={clearAll}>
            Clear all
          </Button>
        </div>
      )}
      <p role="status" className="ap-visually-hidden">
        {status}
      </p>
    </div>
  );
}

export default LibraryFilters;
