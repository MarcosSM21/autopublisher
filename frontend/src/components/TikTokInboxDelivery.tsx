import { useEffect, useRef, useState } from "react";
import { checkPublicationStatus, getTikTokDelivery } from "../api.ts";
import type {
  Publication,
  TikTokDelivery,
  TikTokDeliveryState,
} from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

interface TikTokInboxDeliveryProps {
  publication: Publication;
  /** Called with the publication after a check that changed its status. */
  onChanged: (publication: Publication) => void;
}

const STATE_LABELS: Partial<Record<TikTokDeliveryState, string>> = {
  scheduled: "Scheduled",
  uploading: "Uploading",
  processing: "Processing in TikTok",
  ready: "Ready in TikTok",
  published: "Published",
  failed: "Failed",
};

/**
 * Where a video sent with Upload to Inbox is. Only the delivery is shown: the
 * caption, privacy and every other setting of the final post are chosen in
 * TikTok, so none of them is presented as known here. "Check status" asks TikTok
 * once, only when the video waits in the inbox; it is never polled.
 */
function TikTokInboxDelivery({
  publication,
  onChanged,
}: TikTokInboxDeliveryProps) {
  const [delivery, setDelivery] = useState<TikTokDelivery | null>(null);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A ref, not only state: a double click must never send two checks.
  const pending = useRef(false);

  useEffect(() => {
    let active = true;
    getTikTokDelivery(publication.id)
      .then((loaded) => active && setDelivery(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [publication.id, publication.status]);

  async function check() {
    if (pending.current) {
      return;
    }
    pending.current = true;
    setChecking(true);
    setError(null);
    setResult(null);
    try {
      const checked = await checkPublicationStatus(publication.id);
      setResult(checked.message);
      if (checked.publication.status !== publication.status) {
        onChanged(checked.publication);
      }
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      pending.current = false;
      setChecking(false);
    }
  }

  const label = delivery?.state ? STATE_LABELS[delivery.state] : undefined;
  if (!delivery || !label) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : null;
  }

  return (
    <section aria-label="TikTok delivery" className="notice">
      <p>
        <strong>{label}</strong>
        {delivery.state === "ready" && delivery.delivered_at && (
          <span className="muted">
            {" "}
            · delivered {formatDate(delivery.delivered_at)}
          </span>
        )}
        {delivery.state === "published" && delivery.user_published_at && (
          <span className="muted">
            {" "}
            · seen published in TikTok {formatDate(delivery.user_published_at)}
          </span>
        )}
      </p>
      {delivery.state === "ready" && (
        <>
          <p>{delivery.instruction}</p>
          <p className="muted">
            TikTok inbox notification (not necessarily a phone push
            notification)
          </p>
        </>
      )}
      {delivery.after_delivery_failure && (
        <p className="error">{delivery.after_delivery_failure.message}</p>
      )}
      {delivery.can_check_status && (
        <div className="actions">
          <button type="button" disabled={checking} onClick={check}>
            {checking ? "Checking…" : "Check status"}
          </button>
          <span className="muted">
            Asks TikTok once whether you published it; nothing is uploaded.
          </span>
        </div>
      )}
      {result && <p role="status">{result}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default TikTokInboxDelivery;
