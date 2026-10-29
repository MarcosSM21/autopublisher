import { Link } from "react-router";
import type { PublicationAnalyticsRead } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import { formatWhen } from "../../utils.ts";
import { REFRESH } from "./copy.ts";

interface RefreshStatusProps {
  row: PublicationAnalyticsRead;
  accountsPath: string;
}

/**
 * Where the post's metrics stand. A failure never replaces the last valid
 * reading: the date of that reading stays next to what went wrong.
 */
function RefreshStatus({ row, accountsPath }: RefreshStatusProps) {
  const { refresh, captured_at: capturedAt } = row;
  if (refresh === null) {
    return (
      <p className="ap-analytics__when">
        {capturedAt
          ? `Last valid update: ${formatWhen(capturedAt)}`
          : "Never read."}
      </p>
    );
  }
  const appearance = REFRESH[refresh.status];
  const updating = refresh.status === "pending";
  return (
    <div className="ap-analytics__refresh">
      <Badge tone={appearance.tone} icon={appearance.icon} activity={updating}>
        {appearance.label}
      </Badge>
      <p className="ap-analytics__when">
        {capturedAt
          ? `Last valid update: ${formatWhen(capturedAt)}`
          : updating
            ? "Waiting for its first reading."
            : "No valid reading yet."}
      </p>
      {appearance.failure && (
        <p className="ap-analytics__failure">
          {capturedAt ? "Couldn't update again: " : ""}
          {appearance.failure}
        </p>
      )}
      {refresh.status === "reconnect_required" && (
        <Link className="ap-link" to={accountsPath}>
          Go to Accounts
        </Link>
      )}
    </div>
  );
}

export default RefreshStatus;
