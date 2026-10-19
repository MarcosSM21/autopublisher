import type { Content } from "../../types.ts";
import MediaCard from "./MediaCard.tsx";

interface MediaGridProps {
  contents: Content[];
  selectedId: number | null;
  mediaPath: (id: number) => string;
}

/** The Library grid: a list whose columns fit the space it has (CSS only). */
function MediaGrid({ contents, selectedId, mediaPath }: MediaGridProps) {
  return (
    <ul className="ap-media-grid" aria-label="Media">
      {contents.map((content) => (
        <MediaCard
          key={content.id}
          content={content}
          to={mediaPath(content.id)}
          selected={content.id === selectedId}
        />
      ))}
    </ul>
  );
}

export default MediaGrid;
