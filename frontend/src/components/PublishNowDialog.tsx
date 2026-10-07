import { Fragment, useEffect, useId, useRef, useState } from "react";
import { getPublishCheck, publishNow } from "../api.ts";
import type { Publication, PublishCheck } from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

interface PublishNowDialogProps {
  publication: Publication;
  onCancel: () => void;
  onPublished: (publication: Publication) => void;
}

/**
 * Confirmation before any external effect. The summary comes from the backend's
 * publish check and is shown as-is, so this dialog knows nothing about platforms.
 */
function PublishNowDialog({
  publication,
  onCancel,
  onPublished,
}: PublishNowDialogProps) {
  const [check, setCheck] = useState<PublishCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [remoteChecked, setRemoteChecked] = useState(false);
  // A ref, not only state: a double click must never send two requests.
  const sending = useRef(false);
  const checkboxId = useId();

  useEffect(() => {
    let active = true;
    getPublishCheck(publication.id)
      .then((loaded) => active && setCheck(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [publication.id]);

  async function publish() {
    if (sending.current) {
      return;
    }
    sending.current = true;
    setSubmitting(true);
    setError(null);
    try {
      onPublished(await publishNow(publication.id, remoteChecked));
    } catch (caught) {
      setError(toApiError(caught).message);
      sending.current = false;
      setSubmitting(false);
    }
  }

  const needsRemoteCheck = check?.requires_remote_check ?? false;
  const canPublish =
    check !== null &&
    check.eligible &&
    !submitting &&
    (!needsRemoteCheck || remoteChecked);

  return (
    <section role="dialog" aria-label="Publish now" className="publish-dialog">
      <h4>Publish now</h4>
      {check === null && !error && <p className="muted">Checking…</p>}
      {check && (
        <>
          <dl>
            {check.summary.map((item) => (
              <Fragment key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </Fragment>
            ))}
          </dl>
          {check.scheduled_at && (
            <p className="notice">
              This publication is scheduled for {formatDate(check.scheduled_at)}
              . It will be published now, before its scheduled time.
            </p>
          )}
          {!check.eligible && (
            <ul className="error" aria-label="Problems">
              {check.problems.map((problem) => (
                <li key={`${problem.code}-${problem.field ?? ""}`}>
                  {problem.message}
                </li>
              ))}
            </ul>
          )}
          {needsRemoteCheck && (
            <p className="notice review">
              <input
                id={checkboxId}
                type="checkbox"
                checked={remoteChecked}
                onChange={(event) => setRemoteChecked(event.target.checked)}
              />{" "}
              <label htmlFor={checkboxId}>
                I checked YouTube Studio and this video was not published
              </label>
            </p>
          )}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" disabled={!canPublish} onClick={publish}>
          Publish
        </button>
        <button type="button" disabled={submitting} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

export default PublishNowDialog;
