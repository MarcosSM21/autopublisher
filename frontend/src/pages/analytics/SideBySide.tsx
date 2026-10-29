import type {
  AlignedCell,
  ContentSideBySide,
  PublicationAnalyticsRead,
} from "../../types.ts";
import { platformLabel } from "../../types.ts";
import Card from "../../ui/Card.tsx";
import { ageText, CONTENT_TYPE_LABELS, NUMBER, whyNoMetrics } from "./copy.ts";
import { EngagementItem, MetricItem } from "./PostsTable.tsx";
import RefreshStatus from "./RefreshStatus.tsx";

function CellValue({ cell }: { cell: AlignedCell }) {
  if (cell.metric_name === null) {
    return (
      <span className="ap-analytics__missing">
        No metric for this on {platformLabel(cell.platform)}
      </span>
    );
  }
  if (!cell.available || cell.value === null) {
    return <span className="ap-analytics__missing">Not available</span>;
  }
  return <>{NUMBER.format(cell.value)}</>;
}

interface AlignedRowsProps {
  view: ContentSideBySide;
  labels: Map<number, string>;
}

/**
 * Likes and comments of each publication next to each other, in account
 * order, each with its original name. Every cell looks the same whatever its
 * value: nothing is highlighted, ordered, added up or subtracted.
 */
function AlignedRows({ view, labels }: AlignedRowsProps) {
  return (
    <div className="ap-analytics__aligned">
      {view.aligned.map((row) => (
        <section
          key={row.concept}
          className="ap-analytics__aligned-row"
          aria-labelledby={`aligned-${row.concept}`}
        >
          <h3 id={`aligned-${row.concept}`} className="ap-analytics__title">
            {row.label}
          </h3>
          <p className="ap-meta">{row.definition}</p>
          <dl className="ap-analytics__cells">
            {row.cells.map((cell) => (
              <div key={cell.publication_id} className="ap-analytics__cell">
                <dt>
                  {labels.get(cell.publication_id)}
                  {cell.metric_name && (
                    <>
                      {" "}
                      <code
                        className="ap-analytics__original"
                        title={cell.definition ?? undefined}
                      >
                        {cell.metric_name}
                      </code>
                    </>
                  )}
                </dt>
                <dd>
                  <CellValue cell={cell} />
                </dd>
                {cell.definition && (
                  <p className="ap-analytics__formula">{cell.definition}</p>
                )}
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}

interface PublicationCardProps {
  publication: PublicationAnalyticsRead;
  accountsPath: string;
}

/** One publication with the metrics only its platform has. */
function PublicationCard({ publication, accountsPath }: PublicationCardProps) {
  const titleId = `side-by-side-${publication.publication_id}`;
  const reason = whyNoMetrics(publication);
  const read = publication.captured_at !== null;
  return (
    <Card as="li" className="ap-analytics__post" aria-labelledby={titleId}>
      <div className="ap-analytics__post-head">
        <h3 id={titleId} className="ap-analytics__title">
          {publication.account_label}
        </h3>
        <p className="ap-meta">
          {publication.title ?? "Untitled post"} ·{" "}
          {CONTENT_TYPE_LABELS[publication.content_type]} ·{" "}
          {ageText(publication.age_days)}
        </p>
      </div>
      {reason && <p className="ap-analytics__reason">{reason}</p>}
      {read && publication.metrics.length > 0 && (
        <dl className="ap-analytics__metrics">
          {publication.metrics.map((metric) => (
            <MetricItem key={metric.name} metric={metric} />
          ))}
        </dl>
      )}
      {read && publication.engagement && (
        <dl className="ap-analytics__metrics">
          <EngagementItem engagement={publication.engagement} />
        </dl>
      )}
      {read && publication.metrics.length === 0 && !publication.engagement && (
        <p className="ap-meta">
          No other metrics on {platformLabel(publication.platform)}.
        </p>
      )}
      <div className="ap-analytics__post-foot">
        <RefreshStatus row={publication} accountsPath={accountsPath} />
        {publication.remote_url && (
          <a
            className="ap-link"
            href={publication.remote_url}
            target="_blank"
            rel="noreferrer"
          >
            Open on {platformLabel(publication.platform)}
            <span className="ap-visually-hidden"> (opens in a new tab)</span>
          </a>
        )}
      </div>
    </Card>
  );
}

interface SideBySideProps {
  view: ContentSideBySide;
  accountsPath: string;
}

/**
 * One media's published posts side by side (FR-022). Aligning likes and
 * comments only makes them easy to read together: platforms count them
 * differently, so nothing here is compared, ranked or totalled.
 */
function SideBySide({ view, accountsPath }: SideBySideProps) {
  if (view.per_platform.length === 0) {
    return (
      <p className="ap-meta">
        This media hasn&apos;t been published yet, so it has no metrics.
      </p>
    );
  }
  const labels = new Map(
    view.per_platform.map((p) => [p.publication_id, p.account_label]),
  );
  return (
    <div className="ap-analytics__side-by-side">
      <p className="ap-analytics__note" role="note">
        {view.note}
      </p>
      {view.per_platform.length === 1 && (
        <p className="ap-meta">
          Published on one account only, so there is nothing to show next to it
          yet.
        </p>
      )}
      {view.aligned.length > 0 && (
        <section aria-labelledby="side-by-side-aligned">
          <h2 id="side-by-side-aligned" className="ap-section-title">
            Shown side by side
          </h2>
          <AlignedRows view={view} labels={labels} />
        </section>
      )}
      <section aria-labelledby="side-by-side-each">
        <h2 id="side-by-side-each" className="ap-section-title">
          Each publication
        </h2>
        <p className="ap-meta">
          Views, shares, engagement and other metrics belong to their own
          platform and are only shown here.
        </p>
        <ul className="ap-analytics__posts" aria-label="Each publication">
          {view.per_platform.map((publication) => (
            <PublicationCard
              key={publication.publication_id}
              publication={publication}
              accountsPath={accountsPath}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}

export default SideBySide;
