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

type AssetFilter = "all" | "images" | "videos" | "used" | "unused";

const FILTERS: ReadonlyArray<{ value: AssetFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "images", label: "Images" },
  { value: "videos", label: "Videos" },
  { value: "used", label: "Used" },
  { value: "unused", label: "Unused" },
];

/** Client-side search and filters; "used" comes from the backend (research §2). */
function matches(
  content: Content,
  query: string,
  filter: AssetFilter,
): boolean {
  const needle = query.trim().toLowerCase();
  if (
    needle &&
    !(content.title ?? "").toLowerCase().includes(needle) &&
    !content.original_filename.toLowerCase().includes(needle)
  ) {
    return false;
  }
  switch (filter) {
    case "images":
      return content.media_type === "image";
    case "videos":
      return content.media_type === "video";
    case "used":
      return content.usage.used;
    case "unused":
      return !content.usage.used;
    default:
      return true;
  }
}

interface ContentLibraryProps {
  project: Project;
  /** The selected content comes from the URL. */
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onOpenPosts: (postId?: number) => void;
  /** After an import or a change to a media (e.g. to refresh the project context). */
  onChanged?: () => void;
  /** Whether importing is the next step (see ContentImport `emptyPrimary`). */
  importIsPrimary?: boolean;
}

function ContentLibrary({
  project,
  selectedId,
  onSelect,
  onOpenPosts,
  onChanged,
  importIsPrimary = true,
}: ContentLibraryProps) {
  const [contents, setContents] = useState<Content[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<AssetFilter>("all");

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

  const reloadAfterChange = useCallback(async () => {
    await loadContents();
    onChanged?.();
  }, [loadContents, onChanged]);

  const selected = contents.find((content) => content.id === selectedId);
  const visible = contents.filter((content) => matches(content, query, filter));

  return (
    <div>
      <h3>Asset Library</h3>
      <ContentImport
        project={project}
        onImported={() => void reloadAfterChange()}
        onOpenContent={onSelect}
        empty={loaded && !loadError && contents.length === 0}
        emptyPrimary={importIsPrimary}
      />
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      {contents.length > 0 && (
        <div className="actions">
          <input
            type="search"
            aria-label="Search assets"
            placeholder="Search by title or file name"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <div role="group" aria-label="Filter assets" className="actions">
            {FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={filter === option.value}
                onClick={() => setFilter(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {contents.length > 0 && visible.length === 0 && (
        <p className="muted">No assets match the search and filter.</p>
      )}
      {visible.length > 0 && (
        <ul className="plain content-grid" aria-label="Asset Library">
          {visible.map((content) => (
            <li key={content.id}>
              <button
                type="button"
                className="content-card"
                aria-current={content.id === selectedId}
                onClick={() => onSelect(content.id)}
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
          onChanged={reloadAfterChange}
          onOpenPosts={onOpenPosts}
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
        {usage.used ? usage.platforms.map(platformLabel).join(" · ") : "Unused"}
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
