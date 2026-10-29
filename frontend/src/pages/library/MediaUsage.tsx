import { useId, useState } from "react";
import { Link } from "react-router";
import {
  platformLabel,
  type AssetPublication,
  type PostDisplayState,
} from "../../types.ts";
import Button from "../../ui/Button.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { formatWhen } from "../../utils.ts";

type UsageGroup = "needs_you" | "upcoming" | "drafts" | "published";

const GROUPS: ReadonlyArray<{ key: UsageGroup; title: string }> = [
  { key: "needs_you", title: "Needs you" },
  { key: "upcoming", title: "Upcoming" },
  { key: "drafts", title: "Drafts" },
  { key: "published", title: "Published" },
];

const GROUP_OF: Record<PostDisplayState, UsageGroup | null> = {
  failed: "needs_you",
  needs_review: "needs_you",
  needs_action: "needs_you",
  missed: "needs_you",
  publishing: "upcoming",
  scheduled_automatic: "upcoming",
  scheduled_manual: "upcoming",
  scheduled_paused: "upcoming",
  draft: "drafts",
  published: "published",
  cancelled: null,
};

/** Same order as Posts' Needs you (contracts/ui.md §4). */
const NEEDS_YOU_RANK: Partial<Record<PostDisplayState, number>> = {
  needs_review: 1,
  failed: 2,
  missed: 3,
  needs_action: 4,
};

/** Published rows shown before "Show all". */
const PUBLISHED_PREVIEW = 3;

/** The moment that matters for a row, by its group. */
function relevantDate(publication: AssetPublication, group: UsageGroup) {
  if (group === "published") {
    return publication.published_at;
  }
  if (group === "upcoming" || publication.display_state === "missed") {
    return publication.scheduled_at;
  }
  return publication.updated_at;
}

/** Rows of the Media's Posts by the backend's display state (no readiness). */
function groupUsage(publications: AssetPublication[]) {
  const groups: Record<UsageGroup, AssetPublication[]> = {
    needs_you: [],
    upcoming: [],
    drafts: [],
    published: [],
  };
  let cancelled = 0;
  for (const publication of publications) {
    const group = GROUP_OF[publication.display_state];
    if (group === null) {
      cancelled += 1;
    } else {
      groups[group].push(publication);
    }
  }
  const byDate = (group: UsageGroup, direction: 1 | -1) =>
    groups[group].sort((a, b) => {
      const left = relevantDate(a, group) ?? "";
      const right = relevantDate(b, group) ?? "";
      return direction * left.localeCompare(right);
    });
  byDate("upcoming", 1);
  byDate("published", -1);
  groups.needs_you.sort(
    (a, b) =>
      (NEEDS_YOU_RANK[a.display_state] ?? 9) -
      (NEEDS_YOU_RANK[b.display_state] ?? 9),
  );
  return { groups, cancelled };
}

interface MediaUsageProps {
  projectId: number;
  contentId: number;
  publications: AssetPublication[] | null;
  error: string | null;
  onRetry: () => void;
}

/**
 * Where the Media is used: its Posts grouped as Needs you, Upcoming, Drafts and
 * Published (the latest ones first, then Show all), each row a link to the
 * Post. Cancelled Posts are only counted.
 */
function MediaUsage({
  projectId,
  contentId,
  publications,
  error,
  onRetry,
}: MediaUsageProps) {
  const headingId = useId();
  const [showAll, setShowAll] = useState(false);

  let body;
  if (error) {
    body = (
      <ErrorState
        title="Couldn't load where this media is used"
        message={error}
        onRetry={onRetry}
      />
    );
  } else if (publications === null) {
    body = <Skeleton lines={3} label="Loading usage…" />;
  } else {
    const { groups, cancelled } = groupUsage(publications);
    const used = GROUPS.some(({ key }) => groups[key].length > 0);
    body = (
      <>
        {!used && <p className="ap-meta">Not used yet.</p>}
        {GROUPS.filter(({ key }) => groups[key].length > 0).map(
          ({ key, title }) => {
            const rows =
              key === "published" && !showAll
                ? groups[key].slice(0, PUBLISHED_PREVIEW)
                : groups[key];
            return (
              <section
                key={key}
                className="ap-usage-group"
                aria-labelledby={`${headingId}-${key}`}
              >
                <h4
                  id={`${headingId}-${key}`}
                  className="ap-usage-group__title"
                >
                  {title} · {groups[key].length}
                </h4>
                <ul className="ap-usage-list">
                  {rows.map((publication) => (
                    <UsageRow
                      key={publication.publication_id}
                      projectId={projectId}
                      publication={publication}
                      group={key}
                    />
                  ))}
                </ul>
                {key === "published" &&
                  groups.published.length > PUBLISHED_PREVIEW &&
                  !showAll && (
                    <Button variant="ghost" onClick={() => setShowAll(true)}>
                      Show all {groups.published.length}
                    </Button>
                  )}
                {key === "published" && (
                  <Link
                    className="ap-link"
                    to={`/p/${projectId}/analytics/media/${contentId}`}
                  >
                    See its metrics side by side
                  </Link>
                )}
              </section>
            );
          },
        )}
        {cancelled > 0 && (
          <p className="ap-meta">
            {cancelled} cancelled {cancelled === 1 ? "post" : "posts"}
          </p>
        )}
      </>
    );
  }

  return (
    <section
      className="ap-media-section"
      aria-labelledby={headingId}
      aria-busy={publications === null && !error ? true : undefined}
    >
      <h3 id={headingId} className="ap-media-section__title">
        Usage
      </h3>
      {body}
    </section>
  );
}

function UsageRow({
  projectId,
  publication,
  group,
}: {
  projectId: number;
  publication: AssetPublication;
  group: UsageGroup;
}) {
  const date = relevantDate(publication, group);
  return (
    <li>
      <Link
        className="ap-usage-row"
        to={`/p/${projectId}/posts/${publication.publication_id}`}
      >
        <span className="ap-usage-row__where">
          <strong>{platformLabel(publication.platform)}</strong>{" "}
          <span>{publication.account_name}</span>
        </span>
        <StatusBadge post={publication.display_state} />
        {date && <span className="ap-meta">{formatWhen(date)}</span>}
      </Link>
    </li>
  );
}

export default MediaUsage;
