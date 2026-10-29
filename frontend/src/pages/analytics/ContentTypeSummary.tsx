import type { AnalyticsMedian, ContentTypeSummary } from "../../types.ts";
import Card from "../../ui/Card.tsx";
import {
  CONCEPT_LABELS,
  CONTENT_TYPE_LABELS,
  daysText,
  NUMBER,
  PERCENT,
} from "./copy.ts";

function MedianValue({
  median,
  format,
}: {
  median: AnalyticsMedian;
  format: (value: number) => string;
}) {
  if (median.insufficient_sample || median.value === null) {
    return (
      <span className="ap-analytics__missing">
        Insufficient sample ({median.count}{" "}
        {median.count === 1 ? "post" : "posts"}, 3 needed)
      </span>
    );
  }
  return <>{format(median.value)}</>;
}

function TypeCard({ summary }: { summary: ContentTypeSummary }) {
  const titleId = `analytics-type-${summary.content_type}`;
  return (
    <Card as="li" className="ap-analytics__type" aria-labelledby={titleId}>
      <h3 id={titleId} className="ap-analytics__title">
        {CONTENT_TYPE_LABELS[summary.content_type]}
      </h3>
      <p className="ap-meta">
        {summary.posts_with_data} of {summary.posts_total}{" "}
        {summary.posts_total === 1 ? "post" : "posts"} with metrics
        {summary.median_age_days !== null &&
          ` · median age ${daysText(Math.round(summary.median_age_days))}`}
      </p>
      {summary.insufficient_sample && (
        <p className="ap-analytics__reason">
          Insufficient sample: fewer than 3 posts with metrics, so no median is
          shown as a conclusion.
        </p>
      )}
      <dl className="ap-analytics__metrics">
        {summary.medians.map((median) => (
          <div key={median.name} className="ap-analytics__metric">
            <dt>
              Median{" "}
              {(median.concept && CONCEPT_LABELS[median.concept]) ??
                median.label}{" "}
              <code className="ap-analytics__original">{median.name}</code>
            </dt>
            <dd>
              <MedianValue
                median={median}
                format={(value) => NUMBER.format(value)}
              />
            </dd>
          </div>
        ))}
        {summary.engagement_median && (
          <div className="ap-analytics__metric">
            <dt>Median engagement (calculated)</dt>
            <dd>
              <MedianValue
                median={summary.engagement_median}
                format={(value) => PERCENT.format(value)}
              />
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

interface ContentTypeSummaryProps {
  summaries: ContentTypeSummary[];
}

/**
 * Medians per content type for one account. Each median uses only the posts
 * that have that metric (a real 0 counts, a missing one doesn't); below 3 of
 * them it reads "Insufficient sample". Nothing here spans platforms.
 */
function ContentTypeSummaryList({ summaries }: ContentTypeSummaryProps) {
  if (summaries.length === 0) {
    return <p className="ap-meta">No posts published in this period.</p>;
  }
  return (
    <ul className="ap-analytics__types" aria-label="By content type">
      {summaries.map((summary) => (
        <TypeCard key={summary.content_type} summary={summary} />
      ))}
    </ul>
  );
}

export default ContentTypeSummaryList;
