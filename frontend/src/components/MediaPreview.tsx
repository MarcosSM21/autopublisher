import { useState } from "react";
import type { Content } from "../types.ts";

/**
 * Preview of a content's media from its file URL: an image, or a video (with
 * controls when `large`). Shared by the library, the queue and the publication
 * reviews; it never changes nor copies the file.
 */
function MediaPreview({
  content,
  large = false,
}: {
  content: Pick<Content, "media_type" | "file_url" | "file_available">;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (!content.file_available) {
    return <div className="preview placeholder">File not available</div>;
  }
  if (failed) {
    return (
      <div className="preview placeholder">
        Preview not available in this browser
      </div>
    );
  }
  if (content.media_type === "image") {
    return (
      <img
        className="preview"
        src={content.file_url}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  return large ? (
    <video
      className="preview"
      src={content.file_url}
      controls
      preload="metadata"
      onError={() => setFailed(true)}
    />
  ) : (
    <video
      className="preview"
      src={content.file_url}
      preload="metadata"
      muted
      onError={() => setFailed(true)}
    />
  );
}

export default MediaPreview;
