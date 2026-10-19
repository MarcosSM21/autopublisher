import { useEffect, useState } from "react";
import { listAttempts } from "../../api.ts";
import type { Publication, PublicationAttempt } from "../../types.ts";
import Disclosure from "../../ui/Disclosure.tsx";
import { formatBytes, toApiError } from "../../utils.ts";
import { attemptEvents } from "./activity-events.ts";
import { problemText } from "../../components/platform/problem-copy.ts";

/**
 * What happened to the Post, in words first; the technical details of each
 * attempt only under a second disclosure. Attempts are read when opened, and
 * again when the Post's last attempt changes.
 */
function Activity({ post }: { post: Publication }) {
  const [open, setOpen] = useState(false);
  const [attempts, setAttempts] = useState<PublicationAttempt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = post.latest_attempt;
  const version = `${latest?.id ?? 0}:${latest?.status ?? ""}:${post.display_state}`;

  useEffect(() => {
    if (!open) {
      return;
    }
    let active = true;
    listAttempts(post.id)
      .then((loaded) => {
        if (active) {
          setAttempts(loaded);
          setError(null);
        }
      })
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [open, post.id, version]);

  // The API lists the newest first; events read oldest first.
  const ordered = attempts ? [...attempts].reverse() : [];
  return (
    <section
      className="ap-post-detail__section"
      aria-labelledby="post-activity"
    >
      <h3 id="post-activity" className="ap-post-detail__title">
        Activity
      </h3>
      <Disclosure
        label={
          post.attempt_count > 0
            ? `Show activity (${post.attempt_count})`
            : "Show activity"
        }
        open={open}
        onOpenChange={setOpen}
      >
        {error && <p className="ap-field__error">{error}</p>}
        {attempts !== null && attempts.length === 0 && (
          <p className="ap-meta">Nothing has been sent yet.</p>
        )}
        {ordered.length > 0 && (
          <>
            <ul className="ap-activity">
              {ordered.flatMap((attempt) =>
                attemptEvents(attempt).map((event, index) => (
                  <li key={`${attempt.id}-${index}`}>{event}</li>
                )),
              )}
            </ul>
            <Disclosure label="Technical details">
              <ul className="ap-activity ap-activity--technical">
                {ordered.map((attempt) => (
                  <li key={attempt.id}>
                    <dl className="ap-technical">
                      <dt>Attempt</dt>
                      <dd className="ap-mono">{attempt.id}</dd>
                      <dt>Trigger · status · stage</dt>
                      <dd className="ap-mono">
                        {attempt.trigger} · {attempt.status} · {attempt.stage}
                      </dd>
                      {attempt.error && (
                        <>
                          <dt>Error code</dt>
                          <dd className="ap-mono">{attempt.error.code}</dd>
                          {problemText(
                            attempt.error.message,
                            attempt.error.code,
                          ) !== attempt.error.message && (
                            <>
                              <dt>Error message</dt>
                              <dd>{attempt.error.message}</dd>
                            </>
                          )}
                        </>
                      )}
                      <dt>Sent</dt>
                      <dd className="ap-mono">
                        {formatBytes(attempt.bytes_sent)} of{" "}
                        {formatBytes(attempt.total_bytes)}
                      </dd>
                      <dt>Outcome determined</dt>
                      <dd className="ap-mono">
                        {attempt.outcome_determined === null
                          ? "pending"
                          : String(attempt.outcome_determined)}
                      </dd>
                      {attempt.external_id && (
                        <>
                          <dt>External id</dt>
                          <dd className="ap-mono">{attempt.external_id}</dd>
                        </>
                      )}
                      {typeof attempt.submitted.file_checksum === "string" && (
                        <>
                          <dt>File checksum (SHA-256)</dt>
                          <dd className="ap-mono">
                            {attempt.submitted.file_checksum}
                          </dd>
                        </>
                      )}
                      {typeof attempt.submitted.file_name === "string" && (
                        <>
                          <dt>File</dt>
                          <dd className="ap-mono">
                            {attempt.submitted.file_name}
                          </dd>
                        </>
                      )}
                    </dl>
                  </li>
                ))}
              </ul>
            </Disclosure>
          </>
        )}
      </Disclosure>
    </section>
  );
}

export default Activity;
