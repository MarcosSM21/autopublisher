import { Link } from "react-router";
import ChoiceGroup from "../../../ui/ChoiceGroup.tsx";
import Field from "../../../ui/Field.tsx";
import { WHEN_DATE_ID, type RunKind } from "../final-action.ts";

interface WhenSectionProps {
  when: RunKind;
  onWhenChange: (when: RunKind) => void;
  /** datetime-local value. */
  at: string;
  onAtChange: (at: string) => void;
  error: string | null;
  /** The global automation is paused (overview). */
  paused: boolean;
}

/** The browser's time zone, e.g. "Europe/Madrid". */
function timeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function preview(at: string): string | null {
  const date = new Date(at);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleString(undefined, { dateStyle: "full", timeStyle: "short" });
}

/**
 * Now (default) or Schedule. Scheduling always publishes automatically
 * (R4): there is no manual schedule here. When automation is paused it still
 * schedules, with a warning.
 */
function WhenSection({
  when,
  onWhenChange,
  at,
  onAtChange,
  error,
  paused,
}: WhenSectionProps) {
  const readable = at ? preview(at) : null;
  return (
    <section
      className="ap-publish-section"
      aria-labelledby="publish-when-title"
    >
      <h3 id="publish-when-title" className="ap-publish-section__title">
        When
      </h3>
      <ChoiceGroup
        legend="When should these posts go out?"
        hideLegend
        orientation="horizontal"
        choices={[
          { value: "now", label: "Now" },
          { value: "schedule", label: "Schedule" },
        ]}
        value={when}
        onChange={onWhenChange}
      />
      {when === "schedule" && (
        <div className="ap-when">
          <Field
            id={WHEN_DATE_ID}
            label="Date and time"
            hint={`Time zone: ${timeZone()}`}
            error={error}
            required
          >
            {(control) => (
              <input
                {...control}
                type="datetime-local"
                value={at}
                onChange={(event) => onAtChange(event.target.value)}
              />
            )}
          </Field>
          {readable && <p className="ap-when__preview">{readable}</p>}
          <p className="ap-meta">
            AutoPublisher will publish these posts automatically at this time.
          </p>
          {paused && (
            <p className="ap-notice">
              Automation is paused: these posts won't be published until you
              resume it.{" "}
              <Link className="ap-link" to="/settings">
                Open Settings
              </Link>
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export default WhenSection;
