import { useEffect, useRef, useState } from "react";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import ChoiceGroup from "../../ui/ChoiceGroup.tsx";
import { Sheet } from "../../ui/Dialog.tsx";
import Field from "../../ui/Field.tsx";
import Icon from "../../ui/Icon.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import {
  activeFilters,
  emptyResultsKind,
  FILTER_DIMENSIONS,
  filterControlSelector,
  SORT_OPTIONS,
} from "./library-filters.ts";
import type { FilterKey, LibraryQuery, LibrarySort } from "./library-query.ts";
import { useLibraryQuery } from "./useLibraryQuery.ts";

/**
 * Where focus goes once the URL change of a chip action is rendered: a chip,
 * else the dimension's control (its select from md up, `Filters` below).
 */
type PendingFocus =
  { kind: "chip"; key: FilterKey } | { kind: "control"; key: FilterKey };

/**
 * The Library's search, filters and sort (contracts/ui.md §3–§4, §9), read
 * from and written to the URL through `useLibraryQuery`. From md up the
 * filters are inline selects; below, a `Filters` button opens a Sheet. Only
 * one layout is mounted. `resultCount` is the number of Media the view shows
 * for the current query.
 */
function LibraryFilters({ resultCount }: { resultCount: number }) {
  const { query, search, update, clearSearch, clearFilters, removeFilter } =
    useLibraryQuery();
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [sheetOpen, setSheetOpen] = useState(false);
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
        : filterControlSelector(pending.key);
    root.current?.querySelector<HTMLElement>(selector)?.focus();
  }, [search]);

  function removeChip(key: FilterKey) {
    const index = chips.findIndex((chip) => chip.key === key);
    const neighbour = chips[index + 1] ?? chips[index - 1];
    pendingFocus.current = neighbour
      ? { kind: "chip", key: neighbour.key }
      : { kind: "control", key };
    removeFilter(key);
  }

  function clearAll() {
    pendingFocus.current = { kind: "control", key: "type" };
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
        {isMedium ? (
          FILTER_DIMENSIONS.map((dimension) => (
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
          ))
        ) : (
          <Button
            className="ap-library__filters-button"
            data-filters-button=""
            aria-label={
              chips.length === 0 ? "Filters" : `Filters, ${chips.length} active`
            }
            onClick={() => setSheetOpen(true)}
          >
            {chips.length === 0 ? "Filters" : `Filters · ${chips.length}`}
          </Button>
        )}
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
      {!isMedium && (
        <Sheet
          open={sheetOpen}
          onOpenChange={setSheetOpen}
          title="Filters"
          footer={
            <>
              <Button
                disabled={chips.length === 0}
                onClick={() => {
                  clearFilters();
                  // It turns disabled: focus stays in the Sheet, on Done.
                  document
                    .querySelector<HTMLElement>("[data-filters-done]")
                    ?.focus();
                }}
              >
                Clear filters
              </Button>
              <Button
                variant="primary"
                data-filters-done=""
                onClick={() => setSheetOpen(false)}
              >
                Done
              </Button>
            </>
          }
        >
          {FILTER_DIMENSIONS.map((dimension) => (
            <ChoiceGroup<string>
              key={dimension.key}
              legend={dimension.label}
              className="ap-library__sheet-group"
              choices={[...dimension.options]}
              value={query[dimension.key]}
              // Applied at once: there is no Apply step.
              onChange={(value) =>
                update({ [dimension.key]: value } as Partial<LibraryQuery>)
              }
            />
          ))}
        </Sheet>
      )}
      <p role="status" className="ap-visually-hidden">
        {status}
      </p>
    </div>
  );
}

export default LibraryFilters;
