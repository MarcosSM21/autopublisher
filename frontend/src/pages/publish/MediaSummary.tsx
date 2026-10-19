import MediaPreview from "../../components/MediaPreview.tsx";
import { MEDIA_TYPE_LABELS, type Content } from "../../types.ts";
import { formatDuration } from "../../utils.ts";

/** A compact reminder of what is being published (not the Media detail). */
function MediaSummary({ media }: { media: Content }) {
  return (
    <div className="ap-media-summary">
      <div className="ap-media-summary__preview">
        <MediaPreview content={media} />
      </div>
      <p className="ap-media-summary__text">
        <span className="ap-media-summary__title">
          {media.title ?? media.original_filename}
        </span>
        <span className="ap-meta">
          {MEDIA_TYPE_LABELS[media.media_type]}
          {media.media_type === "video" &&
            media.duration_seconds !== null &&
            ` · ${formatDuration(media.duration_seconds)}`}
        </span>
      </p>
    </div>
  );
}

export default MediaSummary;
