import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";
import {
  createLibraryFolder,
  deleteMediaSelection,
  deleteObject,
  getContent,
  getDeletionPreview,
  getMediaSelectionDeletionPreview,
  listContents,
  listLibraryFolders,
  moveContents,
  renameLibraryFolder,
  type LibraryScope,
} from "../../api.ts";
import DeleteConfirmDialog from "../../components/DeleteConfirmDialog.tsx";
import { parseId } from "../../route-params.ts";
import type { FlashState } from "../../shell/Flash.tsx";
import NotFound from "../../shell/NotFound.tsx";
import {
  MAX_FOLDER_DEPTH,
  type Content,
  type LibraryFolders,
} from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Icon from "../../ui/Icon.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import { useMissingFromProject } from "../useMissingFromProject.ts";
import Breadcrumb, { type Crumb } from "./Breadcrumb.tsx";
import FolderNameDialog from "./FolderNameDialog.tsx";
import FolderPicker from "./FolderPicker.tsx";
import ImportPanel from "./ImportPanel.tsx";
import { libraryResults, searchIndex } from "./library-filters.ts";
import {
  childFolders,
  folderLabel,
  folderPath,
  libraryViewPath,
  locationScope,
} from "./library-folders.ts";
import LibraryFilters from "./LibraryFilters.tsx";
import { libraryReturnParam, selectionKey } from "./library-query.ts";
import LibraryToolbar from "./LibraryToolbar.tsx";
import MediaDetail, { DeleteMediaDialog } from "./MediaDetail.tsx";
import MediaGrid from "./MediaGrid.tsx";
import SelectionBar from "./SelectionBar.tsx";
import { useLibraryQuery } from "./useLibraryQuery.ts";
import { useMediaImport } from "./useMediaImport.ts";
import { usePageDrop } from "./usePageDrop.ts";
import "./library.css";

type ViewKind = LibraryScope["kind"];

type LoadState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error"; message: string }
  | {
      status: "loaded";
      contents: Content[];
      tree: LibraryFolders;
      /** "Now" for the Imported filter: when the list was read (ms). */
      loadedAt: number;
    };

type FolderDialog = "create" | "rename" | "delete" | null;

/** The checked ids and the selection key of the query they were checked in. */
type Checked = { key: string; ids: ReadonlySet<number> } | null;

const NO_CONTENTS: Content[] = [];

/**
 * Where focus goes once a detail closed: its card when the grid shows it, else
 * the shell's main content (FR-082); never the top of the document.
 */
function focusTargetAfterDetail(id: number): HTMLElement | null {
  return (
    document.querySelector<HTMLElement>(`[data-detail-id="${id}"]`) ??
    document.querySelector<HTMLElement>("main")
  );
}

/**
 * What Select acts on (research R8): nothing once the query changed since the
 * ids were checked, else only the checked ids still visible. Null outside
 * Select mode.
 */
function effectiveSelection(
  checked: Checked,
  key: string,
  visibleIds: ReadonlySet<number>,
): ReadonlySet<number> | null {
  if (checked === null) {
    return null;
  }
  if (checked.key !== key) {
    return new Set();
  }
  return new Set([...checked.ids].filter((id) => visibleIds.has(id)));
}

/**
 * /p/:projectId/library/{all,unsorted,folders/:folderId}[/:mediaId] (and the
 * older library/:mediaId, the detail over All media): one Media view for the
 * three kinds. Each view is its own instance, so Select never leaks from one
 * view into another; search, filters and sort live in the URL.
 */
function MediaView({ kind }: { kind: ViewKind }) {
  const { folderId: folderParam } = useParams();
  const folderId = kind === "folder" ? parseId(folderParam) : null;
  const { project } = useProject();
  if (kind === "folder" && folderId === null) {
    return (
      <NotFound
        backTo={{
          to: `/p/${project.id}/library`,
          label: "Back to Library",
        }}
      />
    );
  }
  return (
    <ScopedMediaView
      key={`${kind}:${folderId}`}
      kind={kind}
      folderId={folderId}
    />
  );
}

function ScopedMediaView({
  kind,
  folderId,
}: {
  kind: ViewKind;
  folderId: number | null;
}) {
  const { project, overview, reloadOverview } = useProject();
  const navigate = useNavigate();
  const location = useLocation();
  // Until an account is ready, "Connect an account" (onboarding) leads.
  const importPrimary =
    overview?.projects[0]?.onboarding.account_ready === true;
  const { mediaId } = useParams();
  const selectedId = mediaId === undefined ? null : parseId(mediaId);
  const missing = useMissingFromProject(selectedId, project.id, getContent);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  // Search, filters and sort live in the URL only (research R1).
  const { query, search } = useLibraryQuery();
  const [checked, setChecked] = useState<Checked>(null);
  // The selection as it was when Move was pressed (like Delete's below).
  const [movingIds, setMovingIds] = useState<number[] | null>(null);
  // The selection as it was when Delete was pressed: the dialog confirms
  // exactly these ids, whatever happens to the view's selection meanwhile.
  const [bulkDelete, setBulkDelete] = useState<number[] | null>(null);
  const [folderDialog, setFolderDialog] = useState<FolderDialog>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  // The card menu's target ("Media actions": Move, Delete media).
  const [cardAction, setCardAction] = useState<{
    action: "move" | "delete";
    content: Content;
  } | null>(null);
  // Just deleted or moved out of the view: its URL may still be current for a
  // render while the navigation away is applied (a transition).
  const [closedId, setClosedId] = useState<number | null>(null);
  const scope = useMemo<LibraryScope>(
    () =>
      kind === "folder" && folderId !== null
        ? { kind, folderId }
        : { kind: kind === "unsorted" ? "unsorted" : "all" },
    [kind, folderId],
  );
  const base = `/p/${project.id}/library`;
  const viewPath = libraryViewPath(project.id, scope);
  // A path in this view keeps the Library query (contracts/ui.md §6).
  const withSearch = useCallback((path: string) => path + search, [search]);
  const mediaPath = useCallback(
    (id: number) => withSearch(`${viewPath}/${id}`),
    [viewPath, withSearch],
  );

  // The view's Media and the folder tree (breadcrumb, subfolders, labels and
  // Move destinations), always read again together after a change.
  const load = useCallback(
    () =>
      Promise.all([
        listContents(project.id, scope),
        listLibraryFolders(project.id),
      ])
        .then(([contents, tree]) => {
          const known =
            scope.kind !== "folder" ||
            tree.folders.some((folder) => folder.id === scope.folderId);
          setState(
            known
              ? { status: "loaded", contents, tree, loadedAt: Date.now() }
              : { status: "missing" },
          );
          // A Media that left the view (moved or gone) is no longer selected.
          setChecked(
            (current) =>
              current && {
                key: current.key,
                ids: new Set(
                  contents
                    .map((content) => content.id)
                    .filter((id) => current.ids.has(id)),
                ),
              },
          );
        })
        .catch((caught: unknown) => {
          const error = toApiError(caught);
          setState(
            scope.kind === "folder" && error.status === 404
              ? { status: "missing" }
              : { status: "error", message: error.message },
          );
        }),
    [project.id, scope],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const handleChanged = useCallback(async () => {
    await load();
    reloadOverview();
  }, [load, reloadOverview]);

  const importer = useMediaImport(
    project,
    scope.kind === "folder" ? scope.folderId : null,
    () => void handleChanged(),
  );
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

  // A card that leaves the view (deleted, or moved out of it from its menu)
  // hands focus to its neighbour, else to the main content; never the top of
  // the document. A card that stays keeps it on its own "Media actions".
  const leaving = useRef<{ id: number; neighbour: number | null } | null>(null);
  useEffect(() => {
    const pending = leaving.current;
    if (pending === null || state.status !== "loaded") {
      return;
    }
    leaving.current = null;
    if (document.querySelector(`[data-detail-id="${pending.id}"]`)) {
      return;
    }
    const target =
      (pending.neighbour !== null &&
        document.querySelector<HTMLElement>(
          `[data-detail-id="${pending.neighbour}"]`,
        )) ||
      document.querySelector<HTMLElement>("main");
    target?.focus();
  }, [state]);

  // Closing the detail gives focus back to the card it was opened from, or to
  // the main content when the card is not in the grid (the drawer does the
  // same through `returnFocus`).
  const previous = useRef(selectedId);
  useEffect(() => {
    const closed = previous.current;
    previous.current = selectedId;
    if (closed !== null && selectedId === null) {
      focusTargetAfterDetail(closed)?.focus();
    }
  }, [selectedId]);

  const loaded = state.status === "loaded" ? state : null;
  const contents = loaded?.contents ?? NO_CONTENTS;
  const index = useMemo(() => searchIndex(contents), [contents]);
  // One definition of "visible" for the grid, Select and the bulk actions.
  const loadedAt = loaded?.loadedAt ?? 0;
  const { results, visibleIds } = useMemo(
    () => libraryResults(contents, query, loadedAt, index),
    [contents, query, loadedAt, index],
  );
  const currentKey = selectionKey(query);
  const effective = effectiveSelection(checked, currentKey, visibleIds);
  const folders = loaded?.tree.folders ?? [];
  const folder =
    scope.kind === "folder"
      ? folders.find((item) => item.id === scope.folderId)
      : undefined;
  const title =
    scope.kind === "all"
      ? "All media"
      : scope.kind === "unsorted"
        ? "Unsorted"
        : (folder?.name ?? "Folder");
  const selected = loaded?.contents.find((item) => item.id === selectedId);

  if (
    (mediaId !== undefined && selectedId === null) ||
    missing ||
    state.status === "missing"
  ) {
    return <NotFound backTo={{ to: base, label: "Back to Library" }} />;
  }
  if (
    loaded &&
    selectedId !== null &&
    selectedId !== closedId &&
    selected === undefined &&
    scope.kind !== "all"
  ) {
    // A Media of the project that is not in this view: its detail over All
    // media, which always contains it (a missing one ends in Not found there).
    return <Navigate to={withSearch(`${base}/all/${selectedId}`)} replace />;
  }

  const showingDetail = selected !== undefined;
  const empty = loaded !== null && loaded.contents.length === 0;
  const selecting = effective !== null;
  const subfolders =
    scope.kind === "folder" ? childFolders(folders, scope.folderId) : [];
  const crumbs: Crumb[] = [
    { label: "Library", to: base },
    ...(scope.kind === "folder"
      ? folderPath(folders, scope.folderId).map((item) => ({
          label: item.name,
          to: libraryViewPath(project.id, {
            kind: "folder",
            folderId: item.id,
          }),
        }))
      : [{ label: title, to: viewPath }]),
  ];

  function toggle(id: number) {
    setChecked((current) => {
      const next = new Set(effectiveSelection(current, currentKey, visibleIds));
      if (!next.delete(id)) {
        next.add(id);
      }
      return { key: currentKey, ids: next };
    });
  }

  async function moveChecked(ids: number[], destination: number | null) {
    await moveContents(project.id, ids, destination);
    setMovingIds(null);
    setChecked(null);
    if (selectedId !== null && ids.includes(selectedId)) {
      // The open detail left this view with the others.
      setClosedId(selectedId);
      void navigate(withSearch(viewPath), { replace: true });
    }
    await load();
  }

  async function handleMoved(destination: number | null) {
    const stays =
      scope.kind === "all" ||
      (scope.kind === "unsorted"
        ? destination === null
        : destination === scope.folderId);
    if (stays) {
      await load();
      return;
    }
    // Follow the Media to its new folder: the detail shows where it now is.
    void navigate(
      withSearch(
        `${libraryViewPath(project.id, locationScope(destination))}/${selectedId}`,
      ),
      { replace: true },
    );
  }

  function cardLeaving(id: number) {
    const position = results.findIndex((item) => item.id === id);
    // A Media hidden by the query (a deep link) has no neighbour in the grid.
    const neighbour =
      position < 0
        ? undefined
        : (results[position + 1] ?? results[position - 1]);
    leaving.current = { id, neighbour: neighbour?.id ?? null };
  }

  async function moveOne(content: Content, destination: number | null) {
    await moveContents(project.id, [content.id], destination);
    cardLeaving(content.id);
    setCardAction(null);
    if (content.id === selectedId) {
      await handleMoved(destination);
    } else {
      await load();
    }
  }

  /**
   * Deleted (or already gone): its detail closes back to this view, the view's
   * list, counts and the overview are read again, so no card is left behind.
   */
  async function mediaDeleted(id: number) {
    setCardAction(null);
    // Never read as "not in this view" (→ All media) while leaving it.
    setClosedId(id);
    const state: FlashState = { flash: "Media deleted." };
    if (id === selectedId) {
      // Its card goes with the reload: focus moves on like a card menu's.
      cardLeaving(id);
    }
    await navigate(
      withSearch(id === selectedId ? viewPath : location.pathname),
      {
        replace: true,
        state,
      },
    );
    await handleChanged();
  }

  /**
   * Every selected Media is gone at once: Select mode ends, an open detail of
   * one of them closes back to this view, and the view, counts and overview
   * are read again.
   */
  async function selectionDeleted(ids: number[]) {
    setBulkDelete(null);
    setChecked(null);
    const closing = selectedId !== null && ids.includes(selectedId);
    if (closing) {
      setClosedId(selectedId);
    }
    const state: FlashState = { flash: `${ids.length} media deleted.` };
    await navigate(withSearch(closing ? viewPath : location.pathname), {
      replace: true,
      state,
    });
    await handleChanged();
  }

  /**
   * Some selected Media no longer exist: nothing was deleted. The view is read
   * again, which keeps selected only the Media still in it; the user decides
   * whether to press Delete again.
   */
  async function selectionMissing() {
    setBulkDelete(null);
    const state: FlashState = {
      flash: "Some selected media no longer exist. Review your selection.",
    };
    await navigate(withSearch(location.pathname), { replace: true, state });
    await load();
  }

  /** The deleted folder's parent, or the Library root for a top-level one. */
  function folderDeleted() {
    setFolderDialog(null);
    const parentId = folder?.parent_id ?? null;
    const state: FlashState = { flash: "Folder deleted." };
    void navigate(
      parentId === null
        ? base
        : withSearch(
            libraryViewPath(project.id, { kind: "folder", folderId: parentId }),
          ),
      { replace: true, state },
    );
    reloadOverview();
  }

  const folderMenu = folder && (
    <Disclosure
      label="Folder actions"
      className="ap-menu ap-library__more"
      open={menuOpen}
      onOpenChange={setMenuOpen}
    >
      {folder.depth < MAX_FOLDER_DEPTH && (
        <Button
          onClick={() => {
            setMenuOpen(false);
            setFolderDialog("create");
          }}
        >
          New folder
        </Button>
      )}
      <Button
        onClick={() => {
          setMenuOpen(false);
          setFolderDialog("rename");
        }}
      >
        Rename
      </Button>
      <Button
        className="ap-delete-entry"
        onClick={() => {
          setMenuOpen(false);
          setFolderDialog("delete");
        }}
      >
        Delete folder
      </Button>
    </Disclosure>
  );

  return (
    <div
      className={[
        "ap-library",
        showingDetail ? "ap-library--with-detail" : "",
        drop.dragging ? "ap-library--dragging" : "",
        selecting ? "ap-library--selecting" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      {...drop.handlers}
    >
      {/* Hidden, not unmounted, behind a phone's full-page detail. */}
      <div className="ap-library__list" hidden={showingDetail && !isMedium}>
        <Breadcrumb items={crumbs} />
        <LibraryToolbar
          title={title}
          count={loaded?.contents.length ?? null}
          showImport={loaded !== null}
          importPrimary={importPrimary}
          importDisabledReason={disabledReason}
          importBusy={importer.busy}
          onImport={openPicker}
          onSelect={
            loaded && !empty && !selecting
              ? () => setChecked({ key: currentKey, ids: new Set() })
              : undefined
          }
          actions={folderMenu}
        >
          {loaded && !empty && <LibraryFilters resultCount={results.length} />}
        </LibraryToolbar>
        <ImportPanel
          importer={importer}
          inputRef={inputRef}
          mediaPath={mediaPath}
        />

        {subfolders.length > 0 && (
          <ul className="ap-library-entries" aria-label="Folders">
            {subfolders.map((child) => (
              <li key={child.id}>
                <Link
                  to={libraryViewPath(project.id, {
                    kind: "folder",
                    folderId: child.id,
                  })}
                  className="ap-library-entry"
                >
                  <Icon name="folder" />
                  <span className="ap-library-entry__name">{child.name}</span>
                  <span className="ap-meta">{child.media_count} media</span>
                </Link>
              </li>
            ))}
          </ul>
        )}

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
          <p className="ap-meta">
            {scope.kind === "folder"
              ? "No media in this folder yet."
              : scope.kind === "unsorted"
                ? "No media without a folder."
                : "No media yet."}
          </p>
        )}
        {loaded && !empty && results.length === 0 && (
          <p className="ap-meta">No media match the search and filter.</p>
        )}
        {results.length > 0 && (
          <MediaGrid
            contents={results}
            selectedId={selectedId}
            mediaPath={mediaPath}
            folderLabel={
              scope.kind === "all"
                ? (content) => folderLabel(folders, content.folder_id)
                : undefined
            }
            checkedIds={effective ?? undefined}
            onToggle={selecting ? toggle : undefined}
            onMove={
              selecting
                ? undefined
                : (content) => setCardAction({ action: "move", content })
            }
            onDelete={
              selecting
                ? undefined
                : (content) => setCardAction({ action: "delete", content })
            }
          />
        )}
        {drop.dragging && (
          <p className="ap-library__drop-hint" aria-hidden="true">
            Drop to import
          </p>
        )}
        {effective && (
          <SelectionBar
            count={effective.size}
            onMove={() => setMovingIds([...effective])}
            onDelete={() => setBulkDelete([...effective])}
            onCancel={() => setChecked(null)}
          />
        )}
      </div>

      {selected && loaded && (
        <MediaDetail
          key={selected.id}
          project={project}
          content={selected}
          onChanged={handleChanged}
          folders={folders}
          parentPath={withSearch(viewPath)}
          libraryReturn={libraryReturnParam(scope, query)}
          returnFocus={() => focusTargetAfterDetail(selected.id)}
          sectionTitle={title}
          onMoved={handleMoved}
          onDeleted={() => void mediaDeleted(selected.id)}
        />
      )}
      {cardAction?.action === "move" && (
        <FolderPicker
          title="Move media"
          folders={folders}
          current={cardAction.content.folder_id}
          onMove={(destination) => moveOne(cardAction.content, destination)}
          onStale={() => void load()}
          onClose={() => setCardAction(null)}
        />
      )}
      {cardAction?.action === "delete" && (
        <DeleteMediaDialog
          content={cardAction.content}
          onDeleted={() => {
            cardLeaving(cardAction.content.id);
            void mediaDeleted(cardAction.content.id);
          }}
          onClose={() => setCardAction(null)}
        />
      )}
      {folder && folderDialog === "delete" && (
        <DeleteConfirmDialog
          title="Delete folder?"
          loadPreview={() => getDeletionPreview("folder", folder.id)}
          remove={(confirmation) =>
            deleteObject("folder", folder.id, confirmation)
          }
          onDeleted={folderDeleted}
          onClose={() => setFolderDialog(null)}
        />
      )}
      {bulkDelete && (
        <DeleteConfirmDialog
          title={`Delete ${bulkDelete.length} media item${bulkDelete.length === 1 ? "" : "s"}?`}
          loadPreview={() =>
            getMediaSelectionDeletionPreview(project.id, bulkDelete)
          }
          remove={(confirmation) =>
            deleteMediaSelection(project.id, bulkDelete, confirmation)
          }
          onDeleted={() => void selectionDeleted(bulkDelete)}
          onMissing={() => void selectionMissing()}
          onClose={() => setBulkDelete(null)}
        />
      )}

      {movingIds && (
        <FolderPicker
          title={`Move ${movingIds.length} media`}
          folders={folders}
          current={
            scope.kind === "all"
              ? undefined
              : scope.kind === "unsorted"
                ? null
                : scope.folderId
          }
          onMove={(destination) => moveChecked(movingIds, destination)}
          onStale={() => void load()}
          onClose={() => setMovingIds(null)}
        />
      )}
      {folder && folderDialog === "create" && (
        <FolderNameDialog
          title="New folder"
          submitLabel="Create"
          onSubmit={async (name) => {
            await createLibraryFolder(project.id, name, folder.id);
            setFolderDialog(null);
            await load();
          }}
          onClose={() => setFolderDialog(null)}
        />
      )}
      {folder && folderDialog === "rename" && (
        <FolderNameDialog
          title="Rename folder"
          submitLabel="Save"
          initialName={folder.name}
          onSubmit={async (name) => {
            await renameLibraryFolder(folder.id, name);
            setFolderDialog(null);
            await load();
          }}
          onClose={() => setFolderDialog(null)}
        />
      )}
    </div>
  );
}

export default MediaView;
