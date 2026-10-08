import type { AutoPublishState, Publication } from "../types.ts";

interface AutoPublishBadgeProps {
  publication: Pick<Publication, "auto_publish_state" | "auto_publish_error">;
  /** Whether to add the reason of the last automatic failure, if any. */
  showError?: boolean;
}

/** Second line for an armed publication, by derived state. */
const DETAILS: Partial<Record<AutoPublishState, string>> = {
  waiting: "Waiting for its time",
  due: "Starting soon",
  paused: "Automation paused",
};

/**
 * Automation state of a scheduled publication. "Overdue" is a derived condition of
 * armed publications only: the status stays "scheduled".
 */
function AutoPublishBadge({
  publication,
  showError = true,
}: AutoPublishBadgeProps) {
  const state = publication.auto_publish_state;
  if (state === null) {
    return null;
  }
  const error = showError ? publication.auto_publish_error : null;
  return (
    <span className="auto-publish-badge">
      {state === "overdue" ? (
        <>
          <span className="badge warning">
            Missed automatic publishing window
          </span>{" "}
          <span className="muted">Publish now or reschedule</span>
        </>
      ) : state === "disabled" ? (
        <span className="badge">Auto-publish disabled</span>
      ) : (
        <>
          <span className="badge">Auto-publish enabled</span>{" "}
          <span className={state === "paused" ? "badge warning" : "muted"}>
            {DETAILS[state]}
          </span>
        </>
      )}
      {error && (
        <span className="error">
          {" "}
          Could not start automatically: {error.message}
        </span>
      )}
    </span>
  );
}

export default AutoPublishBadge;
