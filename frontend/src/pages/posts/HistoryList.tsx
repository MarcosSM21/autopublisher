import type { Publication } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import PostRow from "./PostRow.tsx";
import type { MonthGroup } from "./sections.ts";

interface HistoryListProps {
  groups: MonthGroup[];
  total: number;
  shown: number;
  onShowMore: () => void;
  rowPath: (post: Publication) => string;
  selectedId: number | null;
}

/** Published and Cancelled Posts by month, a page at a time (in the client). */
function HistoryList({
  groups,
  total,
  shown,
  onShowMore,
  rowPath,
  selectedId,
}: HistoryListProps) {
  if (total === 0) {
    return <p className="ap-meta">Nothing published or cancelled yet.</p>;
  }
  return (
    <div className="ap-post-sections">
      {groups.map((group) => (
        <section
          key={group.key}
          className="ap-post-section"
          aria-labelledby={`posts-month-${group.key}`}
        >
          <h3 id={`posts-month-${group.key}`} className="ap-post-section__day">
            {group.label}
          </h3>
          <ul className="ap-post-list">
            {group.posts.map((post) => (
              <li key={post.id}>
                <PostRow
                  post={post}
                  to={rowPath(post)}
                  selected={post.id === selectedId}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {shown < total && (
        <div>
          <Button onClick={onShowMore}>Show more</Button>
          <p className="ap-meta">
            Showing {shown} of {total}
          </p>
        </div>
      )}
    </div>
  );
}

export default HistoryList;
