import { useEffect, useState } from "react";
import { listAttempts } from "../api.ts";
import {
  platformLabel,
  type AttemptTrigger,
  type Publication,
  type PublicationAttempt,
} from "../types.ts";
import {
  attemptPercent,
  attemptPhaseLabel,
  formatBytes,
  formatDate,
  isPlatformStage,
  toApiError,
} from "../utils.ts";

interface PublicationAttemptsProps {
  publication: Publication;
  /** Asks the backend to read the platform's status again (read-only). */
  onCheckAgain?: () => void;
}

const TRIGGER_LABELS: Record<AttemptTrigger, string> = {
  manual: "Started manually",
  scheduled: "Started by scheduler",
};

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** An Upload to Inbox attempt that put the video in the user's TikTok inbox. */
function deliveredToInbox(attempt: PublicationAttempt): boolean {
  return (
    attempt.status === "succeeded" &&
    attempt.details.delivered_to_inbox === true
  );
}

/** What happened to the post after the delivery, decided in TikTok. */
const INBOX_FINAL_LABELS: Partial<Record<Publication["status"], string>> = {
  published: "Published in TikTok",
  failed: "Failed in TikTok",
};

/** Progress, result or error of the latest execution, then the history. */
function PublicationAttempts({
  publication,
  onCheckAgain,
}: PublicationAttemptsProps) {
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
      {attempt.status === "failed" && (
        <Failure attempt={attempt} onCheckAgain={onCheckAgain} />
      )}
      <History
        publicationId={publication.id}
        latestId={attempt.id}
        latestStatus={attempt.status}
      />
    </section>
  );
}

function Progress({ attempt }: { attempt: PublicationAttempt }) {
  // While the platform works there is no real percentage: only the phase.
  if (isPlatformStage(attempt)) {
    return (
      <p className="progress" role="status">
        {attemptPhaseLabel(attempt)}…
      </p>
    );
  }
  const percent = attemptPercent(attempt);
  return (
    <div className="progress">
      <progress aria-label="Upload progress" max={1} value={percent / 100} />
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
  const platform = platformLabel(attempt.platform);
  if (deliveredToInbox(attempt)) {
    const final = INBOX_FINAL_LABELS[publication.status];
    return (
      <dl>
        <dt>Delivered to TikTok inbox</dt>
        <dd>{formatDate(attempt.finished_at ?? attempt.started_at)}</dd>
        {final && (
          <>
            <dt>{final}</dt>
            <dd>
              {publication.published_at
                ? formatDate(publication.published_at)
                : "Reported by TikTok"}
            </dd>
          </>
        )}
      </dl>
    );
  }
  return (
    <>
      {attempt.external_url && (
        <p>
          <a
            href={attempt.external_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open on {platform}
          </a>
        </p>
      )}
      <dl>
        {publication.published_at && (
          <>
            <dt>{attempt.platform === "youtube" ? "Uploaded" : "Published"}</dt>
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

function Failure({
  attempt,
  onCheckAgain,
}: {
  attempt: PublicationAttempt;
  onCheckAgain?: () => void;
}) {
  return (
    <>
      {attempt.error && (
        <p className="error" role="alert">
          {attempt.error.message}
        </p>
      )}
      <p className="muted">
        {TRIGGER_LABELS[attempt.trigger]}
        {attempt.error && ` · ${attempt.error.code}`} ·{" "}
        {attempt.requires_manual_review
          ? "Outcome uncertain: manual review required"
          : "Nothing was published"}
      </p>
      {attempt.requires_manual_review && <ManualReview attempt={attempt} />}
      {attempt.requires_manual_review &&
        attempt.error?.code === "tiktok_processing_pending" &&
        onCheckAgain && (
          <div className="actions">
            <button type="button" onClick={onCheckAgain}>
              Check again
            </button>
            <span className="muted">
              Asks TikTok again for the status of the same post; nothing is
              uploaded.
            </span>
          </div>
        )}
    </>
  );
}

function ManualReview({ attempt }: { attempt: PublicationAttempt }) {
  if (attempt.platform === "instagram" || attempt.platform === "threads") {
    return <MetaReview attempt={attempt} />;
  }
  if (attempt.platform === "tiktok") {
    return <TikTokReview attempt={attempt} />;
  }
  if (attempt.platform === "telegram") {
    return <TelegramReview attempt={attempt} />;
  }
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

/**
 * Manual review of an uncertain Telegram message: publishing again reuses the
 * same message identity, so Telegram does not create a second message.
 */
function TelegramReview({ attempt }: { attempt: PublicationAttempt }) {
  const channel = text(attempt.submitted.channel_title);
  return (
    <div className="notice review">
      <strong>Check Telegram</strong>
      <p>
        Telegram did not confirm this message, so it may be in the channel. Look
        for it before publishing again. Publishing again reuses the same message
        identity, so Telegram will not post it twice.
      </p>
      <dl>
        <dt>Channel</dt>
        <dd>{channel ?? "Unknown"}</dd>
        <dt>Time</dt>
        <dd>
          {formatDate(attempt.started_at)}
          {attempt.finished_at && ` – ${formatDate(attempt.finished_at)}`}
        </dd>
      </dl>
    </div>
  );
}

/**
 * Manual review of an uncertain Meta publication (Instagram or Threads): the
 * account, the exact caption or text that was sent and the time, as help to find
 * the post; never as proof.
 */
function MetaReview({ attempt }: { attempt: PublicationAttempt }) {
  const platform = platformLabel(attempt.platform);
  const isThreads = attempt.platform === "threads";
  const username = text(attempt.submitted.username);
  const sent = text(
    isThreads ? attempt.submitted.text : attempt.submitted.caption,
  );
  return (
    <div className="notice review">
      <strong>Check {platform}</strong>
      <p>
        {platform} may have published this post. Look for it before publishing
        again:
      </p>
      <dl>
        <dt>Account</dt>
        <dd>{username ? `@${username}` : "Unknown"}</dd>
        <dt>{isThreads ? "Text" : "Caption"}</dt>
        <dd className="caption">{sent || "(empty)"}</dd>
        <dt>Time</dt>
        <dd>
          {formatDate(attempt.started_at)}
          {attempt.finished_at && ` – ${formatDate(attempt.finished_at)}`}
        </dd>
      </dl>
    </div>
  );
}

/**
 * Manual review of an uncertain TikTok post: TikTok never returns a link for
 * private posts, so the caption and time help to find it on the profile.
 */
function TikTokReview({ attempt }: { attempt: PublicationAttempt }) {
  const account = text(attempt.submitted.creator_nickname);
  const caption = text(attempt.submitted.caption);
  return (
    <div className="notice review">
      <strong>Check TikTok</strong>
      <p>
        TikTok may have published this video: check your TikTok profile before
        publishing again.
      </p>
      <dl>
        <dt>Account</dt>
        <dd>{account ?? "Unknown"}</dd>
        <dt>Caption</dt>
        <dd className="caption">{caption || "(empty)"}</dd>
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
            {deliveredToInbox(item) ? "delivered to TikTok inbox" : item.status}
            {item.error && ` · ${item.error.code}: ${item.error.message}`}
          </li>
        ))}
      </ul>
    </details>
  );
}

export default PublicationAttempts;
