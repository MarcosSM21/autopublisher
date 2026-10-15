import { Fragment, useEffect, useId, useRef, useState } from "react";
import {
  confirmTikTokConsent,
  getPublishCheck,
  getTikTokOptions,
  publishNow,
} from "../api.ts";
import type {
  Publication,
  PublishCheck,
  TikTokPublicationOptions,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

interface PublishNowDialogProps {
  publication: Publication;
  onCancel: () => void;
  onPublished: (publication: Publication) => void;
}

const REMOTE_CHECK_LABELS: Record<string, string> = {
  instagram: "I checked Instagram and this post was not published",
  threads: "I checked Threads and this post was not published",
  tiktok: "I checked TikTok and this video was not published",
};

const INBOX_EXPLANATION =
  "AutoPublisher will upload this video to TikTok. You'll get a TikTok inbox notification to review, edit and publish it.";

/**
 * Confirmation before any external effect. The summary comes from the backend's
 * publish check and is shown as-is. For TikTok Direct Post, the current declaration
 * is always shown and must be accepted in this very action (research §21): the
 * consent is recorded again for the fingerprint shown, and only then is the
 * publication started. Upload to Inbox has no declaration: the user finishes the
 * post in TikTok.
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
  const isTikTok = publication.account.platform === "tiktok";
  const [tiktok, setTikTok] = useState<TikTokPublicationOptions | null>(null);
  const [declarationAccepted, setDeclarationAccepted] = useState(false);
  const inbox = tiktok?.mode === "INBOX_UPLOAD";
  const title = inbox ? "Send to TikTok" : "Publish now";
  // A ref, not only state: a double click must never send two requests.
  const sending = useRef(false);
  const checkboxId = useId();
  const declarationId = useId();

  useEffect(() => {
    let active = true;
    getPublishCheck(publication.id)
      .then((loaded) => active && setCheck(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    if (isTikTok) {
      getTikTokOptions(publication.id)
        .then((loaded) => active && setTikTok(loaded))
        .catch(
          (caught: unknown) => active && setError(toApiError(caught).message),
        );
    }
    return () => {
      active = false;
    };
  }, [publication.id, isTikTok]);

  async function publish() {
    if (sending.current) {
      return;
    }
    sending.current = true;
    setSubmitting(true);
    setError(null);
    try {
      if (isTikTok && !inbox) {
        if (tiktok?.fingerprint == null) {
          throw new Error("Review the TikTok options before publishing.");
        }
        // Fails with `tiktok_consent_stale` if anything changed: nothing is
        // published then.
        await confirmTikTokConsent(
          publication.id,
          tiktok.fingerprint,
          tiktok.declaration.version,
        );
      }
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
    (!needsRemoteCheck || remoteChecked) &&
    (!isTikTok || (tiktok !== null && (inbox || declarationAccepted)));

  return (
    <section role="dialog" aria-label={title} className="publish-dialog">
      <h4>{title}</h4>
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
          {inbox && <p className="notice">{INBOX_EXPLANATION}</p>}
          {isTikTok && tiktok && !inbox && (
            <section aria-label="TikTok declaration" className="notice">
              <p>
                {tiktok.declaration.text}{" "}
                {tiktok.declaration.links.map((link) => (
                  <a
                    key={link.url}
                    href={link.url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    {link.label}
                  </a>
                ))}
              </p>
              <input
                id={declarationId}
                type="checkbox"
                checked={declarationAccepted}
                onChange={(event) =>
                  setDeclarationAccepted(event.target.checked)
                }
              />{" "}
              <label htmlFor={declarationId}>
                I agree to TikTok's declaration for this post
              </label>
              <p className="muted">
                TikTok may take a few minutes to process the video before it
                appears on your profile.
              </p>
            </section>
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
                {REMOTE_CHECK_LABELS[publication.account.platform] ??
                  "I checked YouTube Studio and this video was not published"}
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
          {inbox ? "Send to TikTok" : "Publish"}
        </button>
        <button type="button" disabled={submitting} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

export default PublishNowDialog;
