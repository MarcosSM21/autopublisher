import { Link } from "react-router";
import type { UpcomingPost } from "../../types.ts";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { formatWhen } from "../../utils.ts";

/** The next scheduled posts (the backend sends at most five). */
function UpNext({ posts }: { posts: UpcomingPost[] }) {
  return (
    <section className="ap-home-section" aria-labelledby="home-upnext-title">
      <h2 id="home-upnext-title" className="ap-section-title">
        Up next
      </h2>
      {posts.length === 0 ? (
        <p className="ap-meta">Nothing is scheduled.</p>
      ) : (
        <ul className="ap-home-rows ap-home-timeline">
          {posts.slice(0, 5).map((post) => (
            <li key={post.post_id}>
              <Link
                className="ap-home-row"
                to={`/p/${post.project.id}/posts/${post.post_id}`}
              >
                <span className="ap-home-row__when ap-tabular">
                  {formatWhen(post.scheduled_at)}
                </span>
                <span className="ap-home-row__main">
                  <span className="ap-home-row__title">
                    {post.media_title ?? post.excerpt ?? "Text post"}
                  </span>
                  <span className="ap-meta">
                    {post.project.name} · {post.account.label}
                  </span>
                </span>
                <StatusBadge post={post.display_state} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default UpNext;
