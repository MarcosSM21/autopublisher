import { Link } from "react-router";
import Button from "../../../ui/Button.tsx";
import type { Destination } from "../destinations.ts";
import { DESTINATIONS_ID, destinationRowId } from "../final-action.ts";

/** Why a destination can't be chosen, with where to fix it; or its Draft. */
export function DestinationStatusText({
  destination,
  onAddToTask,
  disabled = false,
}: {
  destination: Destination;
  onAddToTask: (postId: number) => void;
  disabled?: boolean;
}) {
  const { status } = destination;
  if (status.kind === "blocked") {
    return (
      <span className="ap-destination__reason">
        {status.reason}
        {status.action && (
          <>
            {" · "}
            <Link className="ap-link" to={status.action.to}>
              {status.action.label}
            </Link>
          </>
        )}
      </span>
    );
  }
  if (status.kind === "has_draft") {
    return (
      <span className="ap-destination__reason">
        Has a draft
        <Button
          variant="secondary"
          disabled={disabled}
          aria-label={`Add the draft of ${destination.name} to this task`}
          onClick={() => onAddToTask(status.postId)}
        >
          Add to this task
        </Button>
      </span>
    );
  }
  if (status.kind === "member") {
    return <span className="ap-destination__reason">In this task</span>;
  }
  return null;
}

interface DestinationListProps {
  destinations: Destination[];
  selected: number[];
  onToggle: (accountId: number) => void;
  onAddToTask: (postId: number) => void;
  /** Messages per account from a rejected create. */
  errors: Record<number, string[]>;
  disabled: boolean;
  accountsPath: string;
}

/**
 * Compose's destinations: one full row per active account (checkbox and
 * label, ≥ 44 px). Unavailable ones stay visible, disabled, with their
 * reason; an account with a Draft of this Media offers `Add to this task`.
 */
function DestinationList({
  destinations,
  selected,
  onToggle,
  onAddToTask,
  errors,
  disabled,
  accountsPath,
}: DestinationListProps) {
  return (
    <fieldset
      id={DESTINATIONS_ID}
      tabIndex={-1}
      className="ap-publish-section ap-destinations"
      disabled={disabled}
    >
      <legend className="ap-publish-section__title">Destinations</legend>
      {destinations.length === 0 ? (
        <p>
          This project has no active accounts.{" "}
          <Link className="ap-link" to={accountsPath}>
            Add an account
          </Link>
        </p>
      ) : (
        <ul className="ap-destination-list">
          {destinations.map((destination) => {
            const selectable = destination.status.kind === "available";
            const rowErrors = errors[destination.accountId] ?? [];
            return (
              <li
                key={destination.accountId}
                id={destinationRowId(destination.accountId)}
                className={
                  selectable
                    ? "ap-destination"
                    : "ap-destination ap-destination--unavailable"
                }
              >
                <label className="ap-destination__choice">
                  <input
                    type="checkbox"
                    checked={
                      selectable && selected.includes(destination.accountId)
                    }
                    disabled={!selectable}
                    aria-invalid={rowErrors.length > 0 || undefined}
                    onChange={() => onToggle(destination.accountId)}
                  />
                  <span className="ap-destination__name">
                    {destination.name}
                  </span>
                </label>
                <DestinationStatusText
                  destination={destination}
                  onAddToTask={onAddToTask}
                  disabled={disabled}
                />
                {rowErrors.map((message) => (
                  <p key={message} className="ap-field__error">
                    {message}
                  </p>
                ))}
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}

export default DestinationList;
