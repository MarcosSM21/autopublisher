import { useState } from "react";
import { Link } from "react-router";
import { refreshPublicationAnalytics } from "../../api.ts";
import type { Engagement, MetricValue, PostAnalyticsRow } from "../../types.ts";
import { platformLabel } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import Card from "../../ui/Card.tsx";
import { formatWhen, toApiError } from "../../utils.ts";
import {
  ageText,
  CONCEPT_LABELS,
  CONTENT_TYPE_LABELS,
  whyNoMetrics,
  NUMBER,
  PERCENT,
} from "./copy.ts";
import RefreshStatus from "./RefreshStatus.tsx";

export function MetricItem({ metric }: { metric: MetricValue }) {
  const common = metric.concept ? CONCEPT_LABELS[metric.concept] : null;
  return (
    <div className="ap-analytics__metric">
      <dt>
        {common ?? metric.label}{" "}
        <code className="ap-analytics__original" title={metric.definition}>
          {metric.name}
        </code>
      </dt>
      <dd>
        {metric.available && metric.value !== null ? (
          NUMBER.format(metric.value)
        ) : (
          <span className="ap-analytics__missing">Not available</span>
        )}
      </dd>
    </div>
  );
}

export function EngagementItem({ engagement }: { engagement: Engagement }) {
  const components = Object.entries(engagement.components)
    .map(
      ([name, value]) =>
        `${name} ${value === null ? "—" : NUMBER.format(value)}`,
    )
    .join(" · ");
  return (
    <div className="ap-analytics__metric ap-analytics__metric--derived">
      <dt>Engagement (calculated by AutoPublisher)</dt>
      <dd>
        {engagement.available && engagement.value !== null ? (
          PERCENT.format(engagement.value)
        ) : (
          <span className="ap-analytics__missing">Not available</span>
        )}
      </dd>
      <p className="ap-analytics__formula">
        Formula: <code>{engagement.formula}</code>
        <br />
        {components}
      </p>
    </div>
  );
}

interface PostCardProps {
  row: PostAnalyticsRow;
  /** Position in a ranking of one account, if any. */
  rank?: number;
  accountsPath: string;
  /** Where the media's side-by-side view lives (media posts only). */
  mediaPath: (contentId: number) => string;
  onQueued: (row: PostAnalyticsRow) => void;
}

function PostCard({
  row,
  rank,
  accountsPath,
  mediaPath,
  onQueued,
}: PostCardProps) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const reason = whyNoMetrics(row);
  const refreshable =
    row.capability_state === "supported" && row.link_state === "linked";
  const titleId = `analytics-post-${row.publication_id}`;

  async function refresh() {
    setBusy(true);
    setNotice(null);
    try {
      await refreshPublicationAnalytics(row.publication_id);
      setNotice("Update requested. New metrics appear in a minute or so.");
      onQueued(row);
    } catch (caught) {
      const error = toApiError(caught);
      const availableAt = error.details.available_at;
      setNotice(
        error.code === "refresh_cooldown" && typeof availableAt === "string"
          ? `Updated recently. You can refresh again ${formatWhen(availableAt)}.`
          : error.message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card as="li" className="ap-analytics__post" aria-labelledby={titleId}>
      <div className="ap-analytics__post-head">
        <h3 id={titleId} className="ap-analytics__title">
          {rank !== undefined && (
            <span className="ap-analytics__rank">#{rank} </span>
          )}
          {row.title ?? "Untitled post"}
        </h3>
        <p className="ap-meta">
          {row.account_label} · {CONTENT_TYPE_LABELS[row.content_type]} ·{" "}
          {ageText(row.age_days)}
        </p>
      </div>

      {reason && <p className="ap-analytics__reason">{reason}</p>}
      {/* Only a real reading is shown (with a reason, one kept from before);
          a post never read shows its refresh state, not a grid of blanks. */}
      {row.captured_at !== null && row.metrics.length > 0 && (
        <dl className="ap-analytics__metrics">
          {row.metrics.map((metric) => (
            <MetricItem key={metric.name} metric={metric} />
          ))}
          {row.engagement && <EngagementItem engagement={row.engagement} />}
        </dl>
      )}

      <div className="ap-analytics__post-foot">
        <RefreshStatus row={row} accountsPath={accountsPath} />
        <div className="ap-analytics__actions">
          {row.content_id !== null && (
            <Link className="ap-link" to={mediaPath(row.content_id)}>
              Side by side
              <span className="ap-visually-hidden">
                {" "}
                (every account this media was published on)
              </span>
            </Link>
          )}
          {row.remote_url && (
            <a
              className="ap-link"
              href={row.remote_url}
              target="_blank"
              rel="noreferrer"
            >
              Open on {platformLabel(row.platform)}
              <span className="ap-visually-hidden"> (opens in a new tab)</span>
            </a>
          )}
          {refreshable && (
            <Button
              variant="secondary"
              loading={busy}
              onClick={() => void refresh()}
              aria-describedby={titleId}
            >
              Refresh
            </Button>
          )}
        </div>
      </div>
      <p className="ap-analytics__notice" role="status">
        {notice}
      </p>
    </Card>
  );
}

interface PostsTableProps {
  rows: PostAnalyticsRow[];
  /** Numbers the rows #1, #2… (a ranking within one account). */
  ranked?: boolean;
  label?: string;
  accountsPath: string;
  mediaPath: (contentId: number) => string;
  onQueued: (row: PostAnalyticsRow) => void;
}

/**
 * Published posts, each with its own platform's original metrics: newest
 * first, or ranked by one metric of one account. Nothing is added up, averaged
 * or ordered across platforms.
 */
function PostsTable({
  rows,
  ranked = false,
  label = "Published posts",
  accountsPath,
  mediaPath,
  onQueued,
}: PostsTableProps) {
  return (
    <ul className="ap-analytics__posts" aria-label={label}>
      {rows.map((row, index) => (
        <PostCard
          key={row.publication_id}
          row={row}
          rank={ranked ? index + 1 : undefined}
          accountsPath={accountsPath}
          mediaPath={mediaPath}
          onQueued={onQueued}
        />
      ))}
    </ul>
  );
}

export default PostsTable;
