import { useEffect, useState } from "react";
import { getAutomation, setAutomationPaused } from "../api.ts";
import type { AutomationStatus as Status } from "../types.ts";
import Badge from "../ui/Badge.tsx";
import Button from "../ui/Button.tsx";
import Icon from "../ui/Icon.tsx";
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
    <section aria-label="Automation" className="ap-automation">
      {status && (
        <>
          <p className="ap-automation__state">
            <Icon name={status.paused ? "pause" : "check"} />
            <strong>
              {status.paused
                ? "Automatic publishing is paused."
                : "Automatic publishing is running."}
            </strong>
          </p>
          <p className="ap-meta ap-automation__text">
            {status.paused
              ? "Scheduled automatic posts won't publish until you resume it."
              : "Scheduled automatic posts publish at their time."}
            {!status.paused &&
              status.last_check_at &&
              ` Last check ${formatDate(status.last_check_at)}.`}
          </p>
          {!status.running && (
            <Badge tone="warning" icon="alert">
              Scheduler not running
            </Badge>
          )}
          <Button
            variant={status.paused ? "primary" : "secondary"}
            loading={saving}
            onClick={() => void toggle(!status.paused)}
          >
            {status.paused ? "Resume automation" : "Pause automation"}
          </Button>
        </>
      )}
      <p className="ap-meta ap-automation__text">
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
