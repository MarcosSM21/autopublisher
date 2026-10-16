import { useCallback, useEffect, useState } from "react";
import { listContents } from "../api.ts";
import {
  MEDIA_TYPE_LABELS,
  platformLabel,
  type Content,
  type Project,
} from "../types.ts";
import { toApiError } from "../utils.ts";
import ContentDetail from "./ContentDetail.tsx";
import MediaPreview from "./MediaPreview.tsx";
import ContentImport from "./ContentImport.tsx";

interface ContentLibraryProps {
  project: Project;
  onOpenQueue: () => void;
}

function ContentLibrary({ project, onOpenQueue }: ContentLibraryProps) {
  const [contents, setContents] = useState<Content[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // The library is always reloaded from the API after a change.
  const loadContents = useCallback(
    () =>
      listContents(project.id)
        .then((loadedContents) => {
          setContents(loadedContents);
          setLoadError(null);
        })
        .catch((caught: unknown) => setLoadError(toApiError(caught).message))
        .finally(() => setLoaded(true)),
    [project.id],
  );

  useEffect(() => {
    void loadContents();
  }, [loadContents]);

  const selected = contents.find((content) => content.id === selectedId);

  return (
    <div>
      <h3>Asset Library</h3>
      <ContentImport
        project={project}
        onImported={() => void loadContents()}
        onOpenContent={setSelectedId}
      />
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      {loaded && !loadError && contents.length === 0 && (
        <p className="muted">
          No content yet. Drop images or videos here or choose files to import
          them.
        </p>
      )}
      {contents.length > 0 && (
        <ul className="plain content-grid" aria-label="Asset Library">
          {contents.map((content) => (
            <li key={content.id}>
              <button
                type="button"
                className="content-card"
                aria-current={content.id === selectedId}
                onClick={() => setSelectedId(content.id)}
              >
                <AssetCard content={content} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected && (
        <ContentDetail
          key={selected.id}
          project={project}
          content={selected}
          onChanged={loadContents}
          onOpenQueue={onOpenQueue}
        />
      )}
    </div>
  );
}

/** Only what answers "is it used, and where?": no technical data (FR-008). */
function AssetCard({ content }: { content: Content }) {
  const { usage } = content;
  return (
    <>
      <MediaPreview content={content} />
      <span className="content-name">
        {content.title ?? content.original_filename}
      </span>
      <span className="card-badges">
        <span className="badge">{MEDIA_TYPE_LABELS[content.media_type]}</span>
        {content.metadata_status !== "unknown" && (
          <span className="badge">Metadata clean</span>
        )}
      </span>
      <span className="muted">
        {usage.used
          ? usage.platforms.map(platformLabel).join(" · ")
          : "Unused"}
      </span>
      {(usage.scheduled_count > 0 || usage.awaiting_count > 0) && (
        <span className="card-badges">
          {usage.scheduled_count > 0 && (
            <span className="badge status-scheduled">Scheduled</span>
          )}
          {usage.awaiting_count > 0 && (
            <span className="badge">Ready in TikTok</span>
          )}
        </span>
      )}
    </>
  );
}

export default ContentLibrary;
