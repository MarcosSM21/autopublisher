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
import { filterMedia, type LibraryFilter } from "./library-filters.ts";
import {
  childFolders,
  folderLabel,
  folderPath,
  libraryViewPath,
  locationScope,
} from "./library-folders.ts";
import LibraryToolbar from "./LibraryToolbar.tsx";
import MediaDetail, { DeleteMediaDialog } from "./MediaDetail.tsx";
import MediaGrid from "./MediaGrid.tsx";
import SelectionBar from "./SelectionBar.tsx";
import { useMediaImport } from "./useMediaImport.ts";
import { usePageDrop } from "./usePageDrop.ts";
import "./library.css";

type ViewKind = LibraryScope["kind"];

type LoadState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error"; message: string }
  | { status: "loaded"; contents: Content[]; tree: LibraryFolders };

type FolderDialog = "create" | "rename" | "delete" | null;

/**
 * /p/:projectId/library/{all,unsorted,folders/:folderId}[/:mediaId] (and the
 * older library/:mediaId, the detail over All media): one Media view for the
 * three kinds. Each view is its own instance, so search, filters and Select
 * never leak from one view into another.
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
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<LibraryFilter>("all");
  const [checked, setChecked] = useState<ReadonlySet<number> | null>(null);
  const [movingChecked, setMovingChecked] = useState(false);
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
  // Just deleted: its URL may still be current for a render while the
  // navigation away is applied (a transition).
  const [deletedId, setDeletedId] = useState<number | null>(null);
  const scope = useMemo<LibraryScope>(
    () =>
      kind === "folder" && folderId !== null
        ? { kind, folderId }
        : { kind: kind === "unsorted" ? "unsorted" : "all" },
    [kind, folderId],
  );
  const base = `/p/${project.id}/library`;
  const viewPath = libraryViewPath(project.id, scope);
  const mediaPath = useCallback(
    (id: number) => `${viewPath}/${id}`,
    [viewPath],
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
              ? { status: "loaded", contents, tree }
              : { status: "missing" },
          );
          // A Media that left the view (moved or gone) is no longer selected.
          setChecked(
            (current) =>
              current &&
              new Set(
                contents
                  .map((content) => content.id)
                  .filter((id) => current.has(id)),
              ),
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
    selectedId !== deletedId &&
    selected === undefined &&
    scope.kind !== "all"
  ) {
    // A Media of the project that is not in this view: its detail over All
    // media, which always contains it (a missing one ends in Not found there).
    return <Navigate to={`${base}/all/${selectedId}`} replace />;
  }

  const showingDetail = selected !== undefined;
  const empty = loaded !== null && loaded.contents.length === 0;
  const visible = loaded ? filterMedia(loaded.contents, query, filter) : [];
  const selecting = checked !== null;
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
      const next = new Set(current);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  }

  async function moveChecked(destination: number | null) {
    const ids = [...(checked ?? [])];
    await moveContents(project.id, ids, destination);
    setMovingChecked(false);
    setChecked(null);
    if (selectedId !== null && ids.includes(selectedId)) {
      // The open detail left this view with the others.
      void navigate(viewPath, { replace: true });
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
      `${libraryViewPath(project.id, locationScope(destination))}/${selectedId}`,
      { replace: true },
    );
  }

  async function moveOne(content: Content, destination: number | null) {
    await moveContents(project.id, [content.id], destination);
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
    setDeletedId(id);
    const state: FlashState = { flash: "Media deleted." };
    await navigate(id === selectedId ? viewPath : location.pathname, {
      replace: true,
      state,
    });
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
      setDeletedId(selectedId);
    }
    const state: FlashState = { flash: `${ids.length} media deleted.` };
    await navigate(closing ? viewPath : location.pathname, {
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
    await navigate(location.pathname, { replace: true, state });
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
        : libraryViewPath(project.id, { kind: "folder", folderId: parentId }),
      { replace: true, state },
    );
    reloadOverview();
  }

  const folderMenu = folder && (
    <Disclosure
      label="Folder actions"
      className="ap-library__more"
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
          showSearch={loaded !== null && !empty}
          query={query}
          onQueryChange={setQuery}
          filter={filter}
          onFilterChange={setFilter}
          importPrimary={importPrimary}
          importDisabledReason={disabledReason}
          importBusy={importer.busy}
          onImport={openPicker}
          onSelect={
            loaded && !empty && !selecting
              ? () => setChecked(new Set())
              : undefined
          }
          actions={folderMenu}
        />
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
                  <Icon name="library" />
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
        {loaded && !empty && visible.length === 0 && (
          <p className="ap-meta">No media match the search and filter.</p>
        )}
        {visible.length > 0 && (
          <MediaGrid
            contents={visible}
            selectedId={selectedId}
            mediaPath={mediaPath}
            folderLabel={
              scope.kind === "all"
                ? (content) => folderLabel(folders, content.folder_id)
                : undefined
            }
            checkedIds={checked ?? undefined}
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
        {selecting && (
          <SelectionBar
            count={checked.size}
            onMove={() => setMovingChecked(true)}
            onDelete={() => setBulkDelete([...checked])}
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
          parentPath={viewPath}
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
          onDeleted={() => void mediaDeleted(cardAction.content.id)}
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

      {movingChecked && checked && (
        <FolderPicker
          title={`Move ${checked.size} media`}
          folders={folders}
          current={
            scope.kind === "all"
              ? undefined
              : scope.kind === "unsorted"
                ? null
                : scope.folderId
          }
          onMove={moveChecked}
          onStale={() => void load()}
          onClose={() => setMovingChecked(false)}
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
