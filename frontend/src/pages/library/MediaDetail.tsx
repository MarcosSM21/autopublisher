import { useCallback, useEffect, useId, useState } from "react";
import { getContentUsage } from "../../api.ts";
import MediaPreview from "../../components/MediaPreview.tsx";
import {
  MEDIA_TYPE_LABELS,
  platformLabel,
  type AssetPublication,
  type Content,
  type Project,
} from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import DetailSurface from "../../ui/DetailSurface.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { formatDuration, toApiError } from "../../utils.ts";
import FileDetails from "./FileDetails.tsx";
import MediaContentEditor from "./MediaContentEditor.tsx";
import MediaUsage from "./MediaUsage.tsx";

interface MediaDetailProps {
  project: Project;
  content: Content;
  /** After an edit or a file change: reload the Library (and the overview). */
  onChanged: () => Promise<void>;
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
 * Continue publishing), the Media's content, where it is used and, last, the
 * file details. A side panel from xl, a drawer below and a page on phones.
 */
function MediaDetail({ project, content, onChanged }: MediaDetailProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const reasonId = useId();
  const [usage, setUsage] = useState<UsageState>({ status: "loading" });
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
      parentPath={base}
      panelFrom="xl"
      sectionTitle="Library"
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
      </div>
    </DetailSurface>
  );
}

export default MediaDetail;
