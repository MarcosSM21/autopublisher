import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { getContent, listContents } from "../api.ts";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import type { Content } from "../types.ts";
import { MEDIA_MD_UP } from "../ui/breakpoints.ts";
import ErrorState from "../ui/ErrorState.tsx";
import Skeleton from "../ui/Skeleton.tsx";
import { useMediaQuery } from "../ui/useMediaQuery.ts";
import { toApiError } from "../utils.ts";
import ImportPanel from "./library/ImportPanel.tsx";
import { filterMedia, type LibraryFilter } from "./library/library-filters.ts";
import LibraryDropzone from "./library/LibraryDropzone.tsx";
import LibraryToolbar from "./library/LibraryToolbar.tsx";
import MediaDetail from "./library/MediaDetail.tsx";
import MediaGrid from "./library/MediaGrid.tsx";
import { useMediaImport } from "./library/useMediaImport.ts";
import { usePageDrop } from "./library/usePageDrop.ts";
import "./library/library.css";
import { useProject } from "./project-context.ts";
import { useMissingFromProject } from "./useMissingFromProject.ts";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; contents: Content[] };

/**
 * /p/:projectId/library[/:mediaId]: the project's Media as a grid with local
 * search and filters, importing (picker, page drop from md, inline results)
 * and the Media detail chosen by the URL. The grid stays mounted behind the
 * detail, so search, filter and scroll survive opening and closing it.
 */
function LibraryPage() {
  const { project, overview, reloadOverview } = useProject();
  // Until an account is ready, "Connect an account" (onboarding) leads.
  const importPrimary =
    overview?.projects[0]?.onboarding.account_ready === true;
  const { mediaId } = useParams();
  const selectedId = mediaId === undefined ? null : parseId(mediaId);
  const missing = useMissingFromProject(selectedId, project.id, getContent);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const base = `/p/${project.id}/library`;
  const mediaPath = useCallback((id: number) => `${base}/${id}`, [base]);

  // The Library is always reloaded from the API after a change.
  const load = useCallback(
    () =>
      listContents(project.id)
        .then((contents) => setState({ status: "loaded", contents }))
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [project.id],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const handleChanged = useCallback(async () => {
    await load();
    reloadOverview();
  }, [load, reloadOverview]);

  const importer = useMediaImport(project, () => void handleChanged());
  // "Import media" opens the system file picker directly.
  const inputRef = useRef<HTMLInputElement>(null);
  const openPicker = () => inputRef.current?.click();
  const disabledReason = project.is_active
    ? null
    : "Reactivate the project to import media.";
  const drop = usePageDrop(
    isMedium && disabledReason === null,
    (files) => void importer.importFiles(files),
  );

  // Closing the detail gives focus back to the card it was opened from.
  const previous = useRef(selectedId);
  useEffect(() => {
    const closed = previous.current;
    previous.current = selectedId;
    if (closed !== null && selectedId === null) {
      document
        .querySelector<HTMLElement>(`[data-detail-id="${closed}"]`)
        ?.focus();
    }
  }, [selectedId]);

  const loaded = state.status === "loaded" ? state : null;
  const selected = loaded?.contents.find((item) => item.id === selectedId);
  if ((mediaId !== undefined && selectedId === null) || missing) {
    return <NotFound backTo={{ to: base, label: "Back to Library" }} />;
  }

  const showingDetail = selected !== undefined;
  const empty = loaded !== null && loaded.contents.length === 0;
  const visible = loaded ? filterMedia(loaded.contents, query, filter) : [];

  return (
    <div
      className={[
        "ap-library",
        showingDetail ? "ap-library--with-detail" : "",
        drop.dragging ? "ap-library--dragging" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      {...drop.handlers}
    >
      {/* Hidden, not unmounted, behind a phone's full-page detail. */}
      <div className="ap-library__list" hidden={showingDetail && !isMedium}>
        <LibraryToolbar
          showTools={loaded !== null && !empty}
          count={loaded?.contents.length ?? 0}
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          importPrimary={importPrimary}
          importDisabledReason={disabledReason}
          importBusy={importer.busy}
          onImport={openPicker}
        />
        <ImportPanel
          importer={importer}
          inputRef={inputRef}
          mediaPath={mediaPath}
        />

        {state.status === "loading" && (
          <Skeleton lines={4} label="Loading the Library…" />
        )}
        {state.status === "error" && (
          <ErrorState
            title="Couldn't load the Library"
            message={state.message}
            onRetry={() => void load()}
          />
        )}
        {empty && (
          <LibraryDropzone
            canDrop={isMedium}
            dragging={drop.dragging}
            primary={importPrimary}
            disabledReason={disabledReason}
            busy={importer.busy}
            onChoose={openPicker}
          />
        )}
        {loaded && !empty && visible.length === 0 && (
          <p className="ap-meta">No media match the search and filter.</p>
        )}
        {visible.length > 0 && (
          <MediaGrid
            contents={visible}
            selectedId={selectedId}
            mediaPath={mediaPath}
          />
        )}
        {drop.dragging && !empty && (
          <p className="ap-library__drop-hint" aria-hidden="true">
            Drop to import
          </p>
        )}
      </div>

      {selected && (
        <MediaDetail
          key={selected.id}
          project={project}
          content={selected}
          onChanged={handleChanged}
        />
      )}
    </div>
  );
}

export default LibraryPage;
