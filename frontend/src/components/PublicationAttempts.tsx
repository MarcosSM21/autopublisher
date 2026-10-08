import { useEffect, useState } from "react";
import { listAttempts } from "../api.ts";
import type {
  AttemptTrigger,
  Publication,
  PublicationAttempt,
} from "../types.ts";
import { formatBytes, formatDate, toApiError } from "../utils.ts";

interface PublicationAttemptsProps {
  publication: Publication;
}

const TRIGGER_LABELS: Record<AttemptTrigger, string> = {
  manual: "Started manually",
  scheduled: "Started by scheduler",
};

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Progress, result or error of the latest execution, then the history. */
function PublicationAttempts({ publication }: PublicationAttemptsProps) {
  const attempt = publication.latest_attempt;
  if (attempt === null) {
    return null;
  }
  return (
    <section aria-label="Publishing" className="attempt-result">
      {attempt.status === "running" && <Progress attempt={attempt} />}
      {attempt.status === "succeeded" && (
        <Result publication={publication} attempt={attempt} />
      )}
      {attempt.status === "failed" && <Failure attempt={attempt} />}
      <History
        publicationId={publication.id}
        latestId={attempt.id}
        latestStatus={attempt.status}
      />
    </section>
  );
}

function Progress({ attempt }: { attempt: PublicationAttempt }) {
  const percent = Math.round(attempt.progress * 100);
  return (
    <div className="progress">
      <progress aria-label="Upload progress" max={1} value={attempt.progress} />
      <span>
        {percent}% · {formatBytes(attempt.bytes_sent)} of{" "}
        {formatBytes(attempt.total_bytes)}
      </span>
    </div>
  );
}

function Result({
  publication,
  attempt,
}: {
  publication: Publication;
  attempt: PublicationAttempt;
}) {
  const privacy = text(attempt.details.privacy_status);
  const processing = text(attempt.details.processing_status);
  return (
    <>
      {attempt.external_url && (
        <p>
          <a
            href={attempt.external_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open on YouTube
          </a>
        </p>
      )}
      <dl>
        {publication.published_at && (
          <>
            <dt>Uploaded</dt>
            <dd>{formatDate(publication.published_at)}</dd>
          </>
        )}
        {privacy && (
          <>
            <dt>Privacy on YouTube</dt>
            <dd>{privacy}</dd>
          </>
        )}
        {processing && (
          <>
            <dt>Processing</dt>
            <dd>{processing}</dd>
          </>
        )}
      </dl>
      {attempt.warnings.map((warning) => (
        <p key={warning.code} className="notice" role="status">
          {warning.message}
        </p>
      ))}
    </>
  );
}

function Failure({ attempt }: { attempt: PublicationAttempt }) {
  return (
    <>
      {attempt.error && (
        <p className="error" role="alert">
          {attempt.error.message}
        </p>
      )}
      {attempt.requires_manual_review && <ManualReview attempt={attempt} />}
    </>
  );
}

function ManualReview({ attempt }: { attempt: PublicationAttempt }) {
  const channel = text(attempt.submitted.channel_title);
  const channelId = text(attempt.submitted.channel_id);
  const title = text(attempt.submitted.title);
  return (
    <div className="notice review">
      <strong>Check YouTube Studio</strong>
      <p>
        YouTube may have received this video. Look for it before publishing
        again:
      </p>
      <dl>
        <dt>Channel</dt>
        <dd>
          {channel ?? "Unknown"}
          {channelId && ` (${channelId})`}
        </dd>
        <dt>Title</dt>
        <dd>{title ?? "Unknown"}</dd>
        <dt>Time</dt>
        <dd>
          {formatDate(attempt.started_at)}
          {attempt.finished_at && ` – ${formatDate(attempt.finished_at)}`}
        </dd>
      </dl>
    </div>
  );
}

function History({
  publicationId,
  latestId,
  latestStatus,
}: {
  publicationId: number;
  latestId: number;
  latestStatus: string;
}) {
  const [attempts, setAttempts] = useState<PublicationAttempt[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listAttempts(publicationId)
      .then((loaded) => active && setAttempts(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [publicationId, latestId, latestStatus]);

  if (error) {
    return <p className="error">{error}</p>;
  }
  if (attempts.length === 0) {
    return null;
  }
  return (
    <details>
      <summary>Attempts ({attempts.length})</summary>
      <ul className="plain" aria-label="Attempt history">
        {attempts.map((item) => (
          <li key={item.id}>
            {formatDate(item.started_at)} · {TRIGGER_LABELS[item.trigger]} ·{" "}
            {item.status}
            {item.error && ` · ${item.error.code}: ${item.error.message}`}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default PublicationAttempts;
