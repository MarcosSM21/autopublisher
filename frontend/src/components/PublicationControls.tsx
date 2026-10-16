import { useEffect, useRef, useState } from "react";
import { getPublication, getPublishCheck, updatePublication } from "../api.ts";
import {
  type Publication,
  type PublishCheck,
  type TikTokMode,
} from "../types.ts";
import {
  accountName,
  formatDate,
  isFuture,
  isOverdue,
  isTikTokVideo,
  toApiError,
} from "../utils.ts";
import AutoPublishBadge from "./AutoPublishBadge.tsx";
import PublishNowDialog from "./PublishNowDialog.tsx";
import InstagramPublishOptions from "./InstagramPublishOptions.tsx";
import ThreadsPublishOptions from "./ThreadsPublishOptions.tsx";
import TikTokPublishOptions from "./TikTokPublishOptions.tsx";
import YouTubePublishOptions from "./YouTubePublishOptions.tsx";

/**
 * Publish controls shared by the publication detail and the distribution result
 * rows (research.md §8): platform options, Publish now and auto-publish. The live
 * reload is `useLivePublication`; the shared rules live in utils.ts.
 */

/** The platform's own publish options; platforms without them render nothing. */
export function PublicationPlatformOptions({
  publication,
  onSaved,
  onModeChange,
}: {
  publication: Publication;
  onSaved: () => void;
  onModeChange: (mode: TikTokMode | null) => void;
}) {
  return (
    <>
      {publication.account.platform === "youtube" && (
        <YouTubePublishOptions publication={publication} onSaved={onSaved} />
      )}
      {publication.account.platform === "instagram" && (
        <InstagramPublishOptions publication={publication} onSaved={onSaved} />
      )}
      {publication.account.platform === "threads" && (
        <ThreadsPublishOptions publication={publication} onSaved={onSaved} />
      )}
      {isTikTokVideo(publication) && (
        <TikTokPublishOptions
          publication={publication}
          onSaved={onSaved}
          onModeChange={onModeChange}
        />
      )}
    </>
  );
}

export function PublishAction({
  sendToTikTok,
  publication,
  checkVersion,
  dialogOpen,
  onOpen,
  onCancel,
  onPublished,
  onReconciled,
  onCheck,
}: {
  /** Upload to Inbox: the action sends the video to TikTok, it does not post. */
  sendToTikTok: boolean;
  publication: Publication;
  checkVersion: number;
  dialogOpen: boolean;
  onOpen: () => void;
  onCancel: () => void;
  onPublished: (publication: Publication) => void;
  /** The check settled an uncertain attempt: the publication changed. */
  onReconciled: (publication: Publication) => void;
  /** Told the result after each load of the check (null when it failed). */
  onCheck?: (check: PublishCheck | null) => void;
}) {
  const [check, setCheck] = useState<PublishCheck | null>(null);
  // Kept in a ref so a new callback never loads the check again.
  const onCheckRef = useRef(onCheck);
  useEffect(() => {
    onCheckRef.current = onCheck;
  });

  useEffect(() => {
    let active = true;
    getPublishCheck(publication.id)
      .then(async (loaded) => {
        if (!active) {
          return;
        }
        setCheck(loaded);
        onCheckRef.current?.(loaded);
        if (wasReconciled(publication, loaded)) {
          // The backend settled the uncertain attempt while checking: reload
          // once instead of showing a stale status (no polling of the check).
          const current = await getPublication(publication.id);
          if (active) {
            onReconciled(current);
          }
        }
      })
      .catch(() => {
        if (active) {
          setCheck(null);
          onCheckRef.current?.(null);
        }
      });
    return () => {
      active = false;
    };
  }, [publication, checkVersion, onReconciled]);

  if (dialogOpen) {
    return (
      <PublishNowDialog
        publication={publication}
        onCancel={onCancel}
        onPublished={onPublished}
      />
    );
  }
  return (
    <div className="actions">
      <button
        type="button"
        disabled={check === null || !check.eligible}
        onClick={onOpen}
      >
        {sendToTikTok ? "Send to TikTok" : "Publish now"}
      </button>
      {check && !check.eligible && (
        <ul className="muted" aria-label="Why this cannot be published">
          {check.problems.map((problem) => (
            <li key={`${problem.code}-${problem.field ?? ""}`}>
              {problem.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Whether a publish check reflects a reconciliation of the last uncertain attempt
 * (research.md §11b): the remote check is no longer required, or the publication
 * stopped being eligible because the platform confirmed it was published.
 */
function wasReconciled(publication: Publication, check: PublishCheck): boolean {
  const expected = publication.latest_attempt?.requires_manual_review ?? false;
  if (check.requires_remote_check !== expected) {
    return true;
  }
  return (
    publication.status === "failed" &&
    check.problems.some(
      (problem) => problem.code === "publication_not_eligible",
    )
  );
}

/** Current consent of a scheduled publication and the explicit way to change it. */
export function AutoPublishControls({
  publication,
  onSaved,
}: {
  publication: Publication;
  onSaved: (publication: Publication) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const armed = publication.auto_publish_enabled;
  const future = isFuture(publication.scheduled_at);

  async function save(enabled: boolean) {
    setSaving(true);
    setError(null);
    try {
      const saved = await updatePublication(publication.id, {
        auto_publish_enabled: enabled,
      });
      setConfirming(false);
      onSaved(saved);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="auto-publish">
      <p>
        <AutoPublishBadge publication={publication} showError={false} />
      </p>
      {publication.auto_publish_error && (
        <p className="error" role="alert" aria-label="Automatic start failed">
          Could not start automatically:{" "}
          {publication.auto_publish_error.message}{" "}
          <span className="muted">
            ({formatDate(publication.auto_publish_error.failed_at)})
          </span>
        </p>
      )}
      {isOverdue(publication) && publication.auto_publish_window_ends_at && (
        <p className="muted">
          The automatic window ended at{" "}
          {formatDate(publication.auto_publish_window_ends_at)}.
        </p>
      )}
      {confirming ? (
        <section
          role="dialog"
          aria-label="Enable auto-publish"
          className="publish-dialog"
        >
          <h4>Enable auto-publish</h4>
          <p>
            AutoPublisher will publish this on{" "}
            {accountName(publication.account)} automatically at{" "}
            {formatDate(publication.scheduled_at!)}. It must be running at that
            time.
          </p>
          <div className="actions">
            <button type="button" disabled={saving} onClick={() => save(true)}>
              Enable
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : (
        <div className="actions">
          {armed ? (
            <button type="button" disabled={saving} onClick={() => save(false)}>
              Disable auto-publish
            </button>
          ) : (
            <button
              type="button"
              disabled={saving || !future}
              onClick={() => setConfirming(true)}
            >
              Enable auto-publish
            </button>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
