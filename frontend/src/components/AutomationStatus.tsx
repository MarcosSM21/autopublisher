import { useEffect, useState } from "react";
import { getAutomation, setAutomationPaused } from "../api.ts";
import type { AutomationStatus as Status } from "../types.ts";
import { formatDate, toApiError } from "../utils.ts";

interface AutomationStatusProps {
  /** Called after pausing or resuming, e.g. to reload the queue. */
  onChanged?: () => void;
}

/** Global state of automatic publishing with the Pause/Resume action. */
function AutomationStatus({ onChanged }: AutomationStatusProps) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    getAutomation()
      .then((loaded) => active && setStatus(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, []);

  async function toggle(paused: boolean) {
    setSaving(true);
    setError(null);
    try {
      setStatus(await setAutomationPaused(paused));
      onChanged?.();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-label="Automation" className="automation-status">
      {status && (
        <p>
          <strong>
            {status.paused ? "Automation paused" : "Automation running"}
          </strong>
          {!status.running && (
            <span className="badge warning">Scheduler not running</span>
          )}
          {!status.paused && status.last_check_at && (
            <span className="muted">
              {" "}
              · Last check {formatDate(status.last_check_at)}
            </span>
          )}{" "}
          <button
            type="button"
            disabled={saving}
            onClick={() => void toggle(!status.paused)}
          >
            {status.paused ? "Resume automation" : "Pause automation"}
          </button>
        </p>
      )}
      <p className="muted">
        AutoPublisher must be running to publish automatically.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default AutomationStatus;
