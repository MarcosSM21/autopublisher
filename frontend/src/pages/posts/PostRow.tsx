import { Link } from "react-router";
import MediaPreview from "../../components/MediaPreview.tsx";
import type { Publication } from "../../types.ts";
import Icon from "../../ui/Icon.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { accountName, formatWhen, publicationTitle } from "../../utils.ts";
import { calendarMoment } from "./calendar.ts";

interface PostRowProps {
  post: Publication;
  to: string;
  selected: boolean;
  /** Next-action hint (Needs you only). */
  hint?: string | null;
}

/** When the row is about: its relevant moment, or the last edit of a Draft. */
function rowDate(post: Publication): string {
  const moment = calendarMoment(post);
  return moment ? formatWhen(moment) : `Edited ${formatWhen(post.updated_at)}`;
}

/**
 * One Post as a single link: what it is, where it goes, when, its state and,
 * when it needs the user, what to do next. Nothing technical.
 */
function PostRow({ post, to, selected, hint }: PostRowProps) {
  return (
    <Link
      to={to}
      className="ap-post-row"
      data-detail-id={post.id}
      aria-current={selected ? "true" : undefined}
    >
      <span className="ap-post-row__thumb" aria-hidden="true">
        {post.content ? (
          <MediaPreview content={post.content} />
        ) : (
          <Icon name="posts" />
        )}
      </span>
      <span className="ap-post-row__main">
        <span className="ap-post-row__title">{publicationTitle(post)}</span>
        <span className="ap-meta">
          {accountName(post.account)} · {rowDate(post)}
        </span>
        {hint && <span className="ap-post-row__hint">{hint}</span>}
      </span>
      <span className="ap-post-row__status">
        <StatusBadge post={post.display_state} />
      </span>
    </Link>
  );
}

export default PostRow;
