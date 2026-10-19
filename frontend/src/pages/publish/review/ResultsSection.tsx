import { useEffect, useRef } from "react";
import { Link } from "react-router";
import { platformLabel, type Publication } from "../../../types.ts";
import Badge from "../../../ui/Badge.tsx";
import Button from "../../../ui/Button.tsx";
import { accountName } from "../../../utils.ts";
import { aggregateLine, resultView } from "../results.ts";
import type { PostStep } from "../usePublishTask.ts";

interface ResultsSectionProps {
  projectId: number;
  rows: Publication[];
  steps: Record<number, PostStep>;
  /** Move focus to the heading once (after the final action). */
  focus: boolean;
  onFocused: () => void;
}

/**
 * The Posts of the set that already left Draft (and the Drafts the last action
 * couldn't start): one row per Post with its human state, and one aggregate
 * line announced politely. Rebuilt from the real states after a reload.
 */
function ResultsSection({
  projectId,
  rows,
  steps,
  focus,
  onFocused,
}: ResultsSectionProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) {
      heading.current?.focus();
      onFocused();
    }
  }, [focus, onFocused]);
  const views = rows.map((post) => ({
    post,
    view: resultView(post, steps[post.id]),
  }));
  const publishing = views.some(({ view }) => view.outcome === "publishing");
  const base = `/p/${projectId}`;

  return (
    <section
      className="ap-publish-results"
      aria-labelledby="publish-results-title"
    >
      <h2
        id="publish-results-title"
        ref={heading}
        tabIndex={-1}
        className="ap-section-title"
      >
        Results
      </h2>
      <p className="ap-publish-results__aggregate" aria-live="polite">
        {aggregateLine(views.map(({ view }) => view))}
      </p>
      {publishing && (
        <p className="ap-meta">
          Publishing continues in the background. Track it in Posts.
        </p>
      )}
      <ul className="ap-result-list">
        {views.map(({ post, view }) => (
          <li key={post.id} className="ap-result">
            <div className="ap-result__main">
              <span className="ap-result__name">
                {accountName(post.account)}
              </span>
              <Badge tone={view.tone} icon={view.icon}>
                {view.label}
              </Badge>
            </div>
            {view.detail && <p className="ap-meta">{view.detail}</p>}
            {view.problem && (
              <Link className="ap-link" to={`${base}/posts/${post.id}`}>
                Open post
                <span className="ap-visually-hidden">
                  {" "}
                  {accountName(post.account)}
                </span>
              </Link>
            )}
            {view.outcome === "published" &&
              post.latest_attempt?.external_url && (
                <a
                  className="ap-link"
                  href={post.latest_attempt.external_url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Open on {platformLabel(post.account.platform)}
                </a>
              )}
          </li>
        ))}
      </ul>
      <div className="ap-publish-results__actions">
        <Button as="link" to={`${base}/posts`}>
          View posts
        </Button>
        <Button as="link" to={`${base}/library`} variant="ghost">
          Back to Library
        </Button>
      </div>
    </section>
  );
}

export default ResultsSection;
