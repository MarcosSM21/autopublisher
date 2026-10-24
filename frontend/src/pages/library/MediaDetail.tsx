import { useCallback, useEffect, useId, useState } from "react";
import {
  deleteObject,
  getContentUsage,
  getDeletionPreview,
  moveContents,
} from "../../api.ts";
import DeleteConfirmDialog from "../../components/DeleteConfirmDialog.tsx";
import MediaPreview from "../../components/MediaPreview.tsx";
import {
  MEDIA_TYPE_LABELS,
  platformLabel,
  type AssetPublication,
  type Content,
  type LibraryFolder,
  type Project,
} from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import DetailSurface from "../../ui/DetailSurface.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { formatDuration, toApiError } from "../../utils.ts";
import FileDetails from "./FileDetails.tsx";
import FolderPicker from "./FolderPicker.tsx";
import { folderLabel } from "./library-folders.ts";
import MediaContentEditor from "./MediaContentEditor.tsx";
import MediaUsage from "./MediaUsage.tsx";

interface MediaDetailProps {
  project: Project;
  content: Content;
  /** After an edit or a file change: reload the Library (and the overview). */
  onChanged: () => Promise<void>;
  /** The project's folders: the Media's location and where it can move. */
  folders: readonly LibraryFolder[];
  /** Where closing the detail leads: the Library view it was opened from. */
  parentPath: string;
  /** Title of that view (the page's h1). */
  sectionTitle: string;
  /** After a Move: show the Media where it now is. */
  onMoved: (folderId: number | null) => Promise<void>;
  /** Deleted (or already gone): back to the view it was opened from. */
  onDeleted: () => void;
}

type UsageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; publications: AssetPublication[] };

/** Why Publish… can't start, or null. */
function publishBlocker(project: Project, content: Content): string | null {
  if (!project.is_active) {
    return "Reactivate the project to publish.";
  }
  if (!content.file_available) {
    return "The media file is missing, so it can't be published.";
  }
  return null;
}

/**
 * Media detail: preview, identity, the one primary action (Publish… or
 * Continue publishing), the Media's content, where it is used, the file
 * details and, last and apart, Delete media. A side panel from xl, a drawer below and a page on phones.
 */
function MediaDetail({
  project,
  content,
  onChanged,
  folders,
  parentPath,
  sectionTitle,
  onMoved,
  onDeleted,
}: MediaDetailProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const reasonId = useId();
  const [usage, setUsage] = useState<UsageState>({ status: "loading" });
  const [moving, setMoving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const name = content.title ?? content.original_filename;
  const base = `/p/${project.id}/library`;

  const loadUsage = useCallback(
    () =>
      getContentUsage(content.id)
        .then((loaded) =>
          setUsage({ status: "loaded", publications: loaded.publications }),
        )
        .catch((caught: unknown) =>
          setUsage({ status: "error", message: toApiError(caught).message }),
        ),
    [content.id],
  );

  // Read again after every change of the Media (its text, file or Posts).
  useEffect(() => {
    void loadUsage();
  }, [loadUsage, content.updated_at, content.usage]);

  const publications = usage.status === "loaded" ? usage.publications : null;
  const drafts = (publications ?? []).filter(
    (publication) => publication.display_state === "draft",
  );
  const draftCount = content.usage.draft_count;
  const blocker = publishBlocker(project, content);
  const label =
    draftCount === 0
      ? "Publish…"
      : `Continue publishing · ${draftCount} ${draftCount === 1 ? "draft" : "drafts"}`;
  const primary =
    blocker === null ? (
      <Button as="link" to={`${base}/${content.id}/publish`} variant="primary">
        {label}
      </Button>
    ) : (
      <Button variant="primary" disabled aria-describedby={reasonId}>
        {label}
      </Button>
    );

  return (
    <DetailSurface
      title={name}
      parentPath={parentPath}
      panelFrom="xl"
      sectionTitle={sectionTitle}
      actions={isMedium ? undefined : primary}
    >
      <div className="ap-media-detail">
        <div className="ap-media-detail__preview">
          <MediaPreview key={content.id} content={content} large />
        </div>
        <p className="ap-media-detail__identity">
          {MEDIA_TYPE_LABELS[content.media_type]}
          {content.media_type === "video" &&
            ` · ${formatDuration(content.duration_seconds)}`}
          {content.title !== null && (
            <span className="ap-meta"> · {content.original_filename}</span>
          )}
        </p>
        <div className="ap-media-detail__folder">
          <p>Folder: {folderLabel(folders, content.folder_id)}</p>
          <Button onClick={() => setMoving(true)}>Move</Button>
        </div>
        <div className="ap-media-detail__action">
          {isMedium && primary}
          {blocker && (
            <p id={reasonId} className="ap-meta">
              {blocker}
            </p>
          )}
          {blocker === null && drafts.length > 0 && (
            <p className="ap-meta">
              Drafts for{" "}
              {drafts
                .map(
                  (draft) =>
                    `${platformLabel(draft.platform)} · ${draft.account_name}`,
                )
                .join(", ")}
            </p>
          )}
        </div>
        <MediaContentEditor
          content={content}
          publications={publications}
          onSaved={onChanged}
        />
        <MediaUsage
          projectId={project.id}
          publications={publications}
          error={usage.status === "error" ? usage.message : null}
          onRetry={() => void loadUsage()}
        />
        <FileDetails content={content} onChanged={onChanged} />
        <section className="ap-media-detail__danger" aria-label="Delete media">
          <Button className="ap-delete-entry" onClick={() => setDeleting(true)}>
            Delete media
          </Button>
        </section>
      </div>
      {deleting && (
        <DeleteMediaDialog
          content={content}
          onDeleted={onDeleted}
          onClose={() => setDeleting(false)}
        />
      )}
      {moving && (
        <FolderPicker
          title="Move media"
          folders={folders}
          current={content.folder_id}
          onMove={async (folderId) => {
            await moveContents(project.id, [content.id], folderId);
            setMoving(false);
            await onMoved(folderId);
          }}
          onStale={() => void onChanged()}
          onClose={() => setMoving(false)}
        />
      )}
    </DetailSurface>
  );
}

/** The one confirmation of Delete media (detail and card menu). */
export function DeleteMediaDialog({
  content,
  onDeleted,
  onClose,
}: {
  content: Content;
  onDeleted: () => void;
  onClose: () => void;
}) {
  return (
    <DeleteConfirmDialog
      title="Delete media?"
      loadPreview={() => getDeletionPreview("media", content.id)}
      remove={(confirmation) => deleteObject("media", content.id, confirmation)}
      onDeleted={onDeleted}
      onClose={onClose}
    />
  );
}

export default MediaDetail;
