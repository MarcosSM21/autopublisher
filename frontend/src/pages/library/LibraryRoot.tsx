import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { createLibraryFolder, listLibraryFolders } from "../../api.ts";
import type { LibraryFolders } from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Icon from "../../ui/Icon.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import FolderNameDialog from "./FolderNameDialog.tsx";
import ImportPanel from "./ImportPanel.tsx";
import { childFolders, libraryViewPath } from "./library-folders.ts";
import LibraryDropzone from "./LibraryDropzone.tsx";
import LibraryToolbar from "./LibraryToolbar.tsx";
import { useMediaImport } from "./useMediaImport.ts";
import { usePageDrop } from "./usePageDrop.ts";
import "./library.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; tree: LibraryFolders };

/**
 * /p/:projectId/library: the Library's entry points, never a media grid. The
 * top-level folders with their counts, then Unsorted and All media; Import
 * media (to Unsorted) and New folder (top level). A project without Media also
 * gets the onboarding drop zone below the entries.
 */
function LibraryRoot() {
  const { project, overview, reloadOverview } = useProject();
  const importPrimary =
    overview?.projects[0]?.onboarding.account_ready === true;
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [creating, setCreating] = useState(false);
  const base = `/p/${project.id}/library`;

  const load = useCallback(
    () =>
      listLibraryFolders(project.id)
        .then((tree) => setState({ status: "loaded", tree }))
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [project.id],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const importer = useMediaImport(project, null, () => {
    void load();
    reloadOverview();
  });
  const inputRef = useRef<HTMLInputElement>(null);
  const openPicker = () => inputRef.current?.click();
  const disabledReason = project.is_active
    ? null
    : "Reactivate the project to import media.";
  const drop = usePageDrop(
    isMedium && disabledReason === null,
    (files) => void importer.importFiles(files),
  );

  const tree = state.status === "loaded" ? state.tree : null;
  const empty = tree !== null && tree.total_count === 0;
  const entries = tree
    ? [
        ...childFolders(tree.folders, null).map((folder) => ({
          key: `folder-${folder.id}`,
          to: libraryViewPath(project.id, {
            kind: "folder",
            folderId: folder.id,
          }),
          name: folder.name,
          count: folder.media_count,
          virtual: false,
          icon: "folder" as const,
        })),
        {
          key: "unsorted",
          to: `${base}/unsorted`,
          name: "Unsorted",
          count: tree.unsorted_count,
          virtual: true,
          icon: "inbox" as const,
        },
        {
          key: "all",
          to: `${base}/all`,
          name: "All media",
          count: tree.total_count,
          virtual: true,
          icon: "grid" as const,
        },
      ]
    : [];

  return (
    <div
      className={
        drop.dragging
          ? "ap-library ap-library-root ap-library--dragging"
          : "ap-library ap-library-root"
      }
      {...drop.handlers}
    >
      <div className="ap-library__list">
        <LibraryToolbar
          title="Library"
          count={null}
          // An empty Library keeps its one import action in the drop zone.
          showImport={tree !== null && !empty}
          importPrimary={importPrimary}
          importDisabledReason={disabledReason}
          importBusy={importer.busy}
          onImport={openPicker}
          actions={
            tree && (
              <Button icon="plus" onClick={() => setCreating(true)}>
                New folder
              </Button>
            )
          }
        />
        <ImportPanel
          importer={importer}
          inputRef={inputRef}
          mediaPath={(id) => `${base}/all/${id}`}
        />

        {state.status === "loading" && (
          <Skeleton lines={3} label="Loading the Library…" />
        )}
        {state.status === "error" && (
          <ErrorState
            title="Couldn't load the Library"
            message={state.message}
            onRetry={() => void load()}
          />
        )}
        {tree && (
          <ul className="ap-library-entries" aria-label="Library">
            {entries.map((entry) => (
              <li key={entry.key}>
                <Link
                  to={entry.to}
                  className={
                    entry.virtual
                      ? "ap-library-entry ap-library-entry--virtual"
                      : "ap-library-entry"
                  }
                >
                  <Icon name={entry.icon} />
                  <span className="ap-library-entry__name">{entry.name}</span>
                  <span className="ap-meta">{entry.count} media</span>
                </Link>
              </li>
            ))}
          </ul>
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
        {drop.dragging && !empty && (
          <p className="ap-library__drop-hint" aria-hidden="true">
            Drop to import
          </p>
        )}
      </div>

      {creating && (
        <FolderNameDialog
          title="New folder"
          submitLabel="Create"
          onSubmit={async (name) => {
            await createLibraryFolder(project.id, name, null);
            setCreating(false);
            await load();
          }}
          onClose={() => setCreating(false)}
        />
      )}
    </div>
  );
}

export default LibraryRoot;
