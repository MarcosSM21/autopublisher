import { useCallback, useEffect, useState } from "react";
import { listContents } from "../api.ts";
import { MEDIA_TYPE_LABELS, type Content, type Project } from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";
import ContentDetail, { MediaPreview } from "./ContentDetail.tsx";
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
        <ul className="plain content-grid" aria-label="Content library">
          {contents.map((content) => (
            <li key={content.id}>
              <button
                type="button"
                className="content-card"
                aria-current={content.id === selectedId}
                onClick={() => setSelectedId(content.id)}
              >
                <MediaPreview content={content} />
                <span className="badge">
                  {MEDIA_TYPE_LABELS[content.media_type]}
                </span>
                <span className="content-name">
                  {content.title ?? content.original_filename}
                </span>
                <span className="muted">{formatDate(content.created_at)}</span>
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

export default ContentLibrary;
