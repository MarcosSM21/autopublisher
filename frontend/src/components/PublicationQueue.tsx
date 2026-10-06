import { useCallback, useEffect, useState } from "react";
import { listPublications } from "../api.ts";
import {
  PUBLICATION_STATUS_LABELS,
  type Project,
  type Publication,
  type PublicationStatus,
} from "../types.ts";
import { accountName, formatDate, isOverdue, toApiError } from "../utils.ts";
import { MediaPreview } from "./ContentDetail.tsx";
import PublicationDetail from "./PublicationDetail.tsx";

interface PublicationQueueProps {
  project: Project;
}

const SECTIONS: PublicationStatus[] = ["scheduled", "unscheduled", "cancelled"];

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
          {isOverdue(publication) && (
            <span className="badge warning">Overdue</span>
          )}
          {!publication.account.is_active && (
            <span className="badge warning">Account inactive</span>
          )}
        </span>
        {publication.scheduled_at && (
          <span className="muted">{formatDate(publication.scheduled_at)}</span>
        )}
      </span>
    </button>
  );
}

export default PublicationQueue;
