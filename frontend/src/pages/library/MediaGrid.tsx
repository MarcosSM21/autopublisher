import type { Content } from "../../types.ts";
import MediaCard from "./MediaCard.tsx";

interface MediaGridProps {
  contents: Content[];
  selectedId: number | null;
  mediaPath: (id: number) => string;
  /** Each card's folder (All media only). */
  folderLabel?: (content: Content) => string;
  /** Select mode: the checked ids and how to toggle one. */
  checkedIds?: ReadonlySet<number>;
  onToggle?: (id: number) => void;
  /** Each card's "Media actions" (Move, Delete media). */
  onMove?: (content: Content) => void;
  onDelete?: (content: Content) => void;
  /** Just created by an import: highlighted once (Feature 026). */
  importedIds?: ReadonlySet<number>;
  onHighlightEnd?: (id: number) => void;
}

/** The Library grid: a list whose columns fit the space it has (CSS only). */
function MediaGrid({
  contents,
  selectedId,
  mediaPath,
  folderLabel,
  checkedIds,
  onToggle,
  onMove,
  onDelete,
  importedIds,
  onHighlightEnd,
}: MediaGridProps) {
  return (
    <ul className="ap-media-grid" aria-label="Media">
      {contents.map((content) => (
        <MediaCard
          key={content.id}
          content={content}
          to={mediaPath(content.id)}
          selected={content.id === selectedId}
          folderLabel={folderLabel?.(content)}
          checked={checkedIds?.has(content.id)}
          onToggle={onToggle && (() => onToggle(content.id))}
          onMove={onMove && (() => onMove(content))}
          onDelete={onDelete && (() => onDelete(content))}
          justImported={importedIds?.has(content.id)}
          onHighlightEnd={onHighlightEnd && (() => onHighlightEnd(content.id))}
        />
      ))}
    </ul>
  );
}

export default MediaGrid;
