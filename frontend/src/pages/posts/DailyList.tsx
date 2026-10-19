import type { RefObject } from "react";
import type { Publication } from "../../types.ts";
import { rowHint } from "./post-actions.ts";
import PostRow from "./PostRow.tsx";
import { readinessOf, type ReadinessSource } from "./readiness.ts";
import type { DailySections } from "./sections.ts";

interface DailyListProps {
  sections: DailySections;
  readiness: ReadinessSource;
  rowPath: (post: Publication) => string;
  selectedId: number | null;
  draftsHeading: RefObject<HTMLHeadingElement | null>;
}

function Rows({
  posts,
  rowPath,
  selectedId,
  hint,
}: {
  posts: Publication[];
  rowPath: (post: Publication) => string;
  selectedId: number | null;
  hint?: (post: Publication) => string | null;
}) {
  return (
    <ul className="ap-post-list">
      {posts.map((post) => (
        <li key={post.id}>
          <PostRow
            post={post}
            to={rowPath(post)}
            selected={post.id === selectedId}
            hint={hint?.(post)}
          />
        </li>
      ))}
    </ul>
  );
}

/**
 * The daily list by meaning: Needs you (with what to do), Upcoming (what's
 * publishing now, then by day) and Drafts. Empty sections are hidden.
 */
function DailyList({
  sections,
  readiness,
  rowPath,
  selectedId,
  draftsHeading,
}: DailyListProps) {
  const { needsYou, publishing, upcoming, drafts } = sections;
  const upcomingCount =
    publishing.length +
    upcoming.reduce((total, group) => total + group.posts.length, 0);
  return (
    <div className="ap-post-sections">
      {needsYou.length > 0 && (
        <section className="ap-post-section" aria-labelledby="posts-needs-you">
          <h2 id="posts-needs-you" className="ap-section-title">
            Needs you · {needsYou.length}
          </h2>
          <Rows
            posts={needsYou}
            rowPath={rowPath}
            selectedId={selectedId}
            hint={(post) => rowHint(post, readinessOf(post, readiness))}
          />
        </section>
      )}
      {upcomingCount > 0 && (
        <section className="ap-post-section" aria-labelledby="posts-upcoming">
          <h2 id="posts-upcoming" className="ap-section-title">
            Upcoming · {upcomingCount}
          </h2>
          {publishing.length > 0 && (
            <section aria-labelledby="posts-publishing">
              <h3 id="posts-publishing" className="ap-post-section__day">
                Publishing now
              </h3>
              <Rows
                posts={publishing}
                rowPath={rowPath}
                selectedId={selectedId}
              />
            </section>
          )}
          {upcoming.map((group) => (
            <section key={group.key} aria-labelledby={`posts-day-${group.key}`}>
              <h3
                id={`posts-day-${group.key}`}
                className="ap-post-section__day"
              >
                {group.label}
              </h3>
              <Rows
                posts={group.posts}
                rowPath={rowPath}
                selectedId={selectedId}
              />
            </section>
          ))}
        </section>
      )}
      {drafts.length > 0 && (
        <section className="ap-post-section" aria-labelledby="posts-drafts">
          <h2
            id="posts-drafts"
            ref={draftsHeading}
            tabIndex={-1}
            className="ap-section-title"
          >
            Drafts · {drafts.length}
          </h2>
          <Rows posts={drafts} rowPath={rowPath} selectedId={selectedId} />
        </section>
      )}
    </div>
  );
}

export default DailyList;
