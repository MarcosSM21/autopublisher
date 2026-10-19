import { Link } from "react-router";
import MediaPreview from "../../components/MediaPreview.tsx";
import type { Content } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import { formatDuration } from "../../utils.ts";
import { usageIndicator } from "./usage-indicator.ts";

interface MediaCardProps {
  content: Content;
  to: string;
  selected: boolean;
}

/**
 * One Media in the grid, as a single link: preview, duration (videos), title or
 * file name and one usage indicator. No technical data.
 */
function MediaCard({ content, to, selected }: MediaCardProps) {
  const indicator = usageIndicator(content.usage);
  return (
    <li>
      <Link
        to={to}
        className={
          selected ? "ap-media-card ap-media-card--selected" : "ap-media-card"
        }
        aria-current={selected ? "true" : undefined}
        data-detail-id={content.id}
      >
        <span className="ap-media-card__preview">
          <MediaPreview content={content} />
          {content.media_type === "video" &&
            content.duration_seconds !== null && (
              <span className="ap-media-card__duration">
                <span className="ap-visually-hidden">Duration </span>
                {formatDuration(content.duration_seconds)}
              </span>
            )}
        </span>
        <span className="ap-media-card__title">
          {content.title ?? content.original_filename}
        </span>
        {indicator && (
          <Badge tone={indicator.tone} icon={indicator.icon}>
            {indicator.label}
          </Badge>
        )}
      </Link>
    </li>
  );
}

export default MediaCard;
