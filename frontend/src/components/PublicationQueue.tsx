import { useCallback, useEffect, useState } from "react";
import { listPublications } from "../api.ts";
import {
  PUBLICATION_STATUS_LABELS,
  type Project,
  type Publication,
  type PublicationStatus,
} from "../types.ts";
import {
  AUTOMATION_POLL_INTERVAL_MS,
  accountName,
  awaitsAutomaticStart,
  formatDate,
  toApiError,
} from "../utils.ts";
import AutomationStatus from "./AutomationStatus.tsx";
import AutoPublishBadge from "./AutoPublishBadge.tsx";
import { MediaPreview } from "./ContentDetail.tsx";
import PublicationDetail from "./PublicationDetail.tsx";

interface PublicationQueueProps {
  project: Project;
}

/** Queue order of research.md §14 (the API already returns items in it). */
const SECTIONS: PublicationStatus[] = [
  "publishing",
  "failed",
  "scheduled",
  "unscheduled",
  "published",
  "cancelled",
];
/** Sections shown even when empty. */
const ALWAYS_SHOWN: PublicationStatus[] = [
  "scheduled",
  "unscheduled",
  "cancelled",
];
/** How often the queue is reloaded while something is being published. */
export const QUEUE_POLL_INTERVAL_MS = 2000;

function PublicationQueue({ project }: PublicationQueueProps) {
  const [publications, setPublications] = useState<Publication[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The queue is always reloaded from the API after a change; the API already
  // returns it in queue order (contracts/api.md).
  const load = useCallback(
    () =>
      listPublications(project.id)
        .then((loadedPublications) => {
          setPublications(loadedPublications);
          setLoadError(null);
        })
        .catch((caught: unknown) => setLoadError(toApiError(caught).message))
        .finally(() => setLoaded(true)),
    [project.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Fast polling while uploads run; slower polling while armed publications wait,
  // so that a start by the scheduler shows up without a manual reload.
  const pollInterval = publications.some(
    (publication) => publication.status === "publishing",
  )
    ? QUEUE_POLL_INTERVAL_MS
    : publications.some(awaitsAutomaticStart)
      ? AUTOMATION_POLL_INTERVAL_MS
      : null;
  useEffect(() => {
    if (pollInterval === null) {
      return;
    }
    const timer = window.setInterval(() => void load(), pollInterval);
    return () => window.clearInterval(timer);
  }, [pollInterval, load]);

  function select(id: number) {
    setSelectedId(id);
    setNotice(null);
  }

  async function handleChanged(message?: string) {
    setNotice(message ?? null);
    await load();
  }

  const selected = publications.find(
    (publication) => publication.id === selectedId,
  );

  return (
    <div>
      <h3>Queue</h3>
      <AutomationStatus onChanged={() => void load()} />
      {!project.is_active && (
        <p className="muted">
          This project is inactive: its publications can be viewed but not
          scheduled.
        </p>
      )}
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      {loaded && !loadError && publications.length === 0 && (
        <p className="muted">
          No publications yet. Open a content and choose Prepare publications.
        </p>
      )}
      {publications.length > 0 && (
        <section aria-label="Publication queue">
          {SECTIONS.map((status) => {
            const items = publications.filter(
              (publication) => publication.status === status,
            );
            if (items.length === 0 && !ALWAYS_SHOWN.includes(status)) {
              return null;
            }
            const label = PUBLICATION_STATUS_LABELS[status];
            return (
              <div key={status} className="queue-section">
                <h4>
                  {label} ({items.length})
                </h4>
                {items.length > 0 && (
                  <ul className="plain" aria-label={`${label} publications`}>
                    {items.map((publication) => (
                      <li key={publication.id}>
                        <QueueRow
                          publication={publication}
                          selected={publication.id === selectedId}
                          onSelect={() => select(publication.id)}
                        />
                        <ResultLink publication={publication} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </section>
      )}
      {notice && <p role="status">{notice}</p>}
      {selected && (
        <PublicationDetail
          key={`${selected.id}-${selected.status}`}
          publication={selected}
          onChanged={handleChanged}
        />
      )}
    </div>
  );
}

function QueueRow({
  publication,
  selected,
  onSelect,
}: {
  publication: Publication;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className="queue-row"
      aria-current={selected}
      onClick={onSelect}
    >
      <MediaPreview content={publication.content} />
      <span className="queue-text">
        <span className="content-name">
          {publication.content.title ?? publication.content.original_filename}
        </span>
        <span>{accountName(publication.account)}</span>
        <span>
          <span className={`badge status-${publication.status}`}>
            {PUBLICATION_STATUS_LABELS[publication.status]}
          </span>
          {!publication.account.is_active && (
            <span className="badge warning">Account inactive</span>
          )}
        </span>
        {publication.scheduled_at && (
          <span className="muted">{formatDate(publication.scheduled_at)}</span>
        )}
        <AutoPublishBadge publication={publication} />
        <ExecutionSummary publication={publication} />
      </span>
    </button>
  );
}

/** Progress, warnings or the last error of the latest attempt. */
function ExecutionSummary({ publication }: { publication: Publication }) {
  const attempt = publication.latest_attempt;
  if (attempt === null) {
    return null;
  }
  if (publication.status === "publishing" && attempt.status === "running") {
    return (
      <span className="muted">
        Uploading {Math.round(attempt.progress * 100)}%
      </span>
    );
  }
  if (publication.status === "published" && attempt.warnings.length > 0) {
    return <span className="badge warning">Privacy differs</span>;
  }
  if (publication.status === "failed" && attempt.error) {
    return (
      <>
        <span className="error">{attempt.error.message}</span>
        {attempt.requires_manual_review && (
          <span className="badge warning">Manual review required</span>
        )}
      </>
    );
  }
  return null;
}

/** Kept outside the row button: a link cannot live inside a button. */
function ResultLink({ publication }: { publication: Publication }) {
  const url = publication.latest_attempt?.external_url;
  if (publication.status !== "published" || !url) {
    return null;
  }
  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      Open on YouTube
    </a>
  );
}

export default PublicationQueue;
