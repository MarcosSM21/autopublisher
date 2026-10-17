import { useCallback, useEffect, useState } from "react";
import { listPlatforms } from "../../api.ts";
import type { PlatformAvailability } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { toApiError } from "../../utils.ts";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; platforms: PlatformAvailability[] };

/**
 * One compact row per integration: its state and, when something is missing,
 * the backend's already-sanitised message. Read-only: configuration itself
 * stays outside the UI (no paths, values or secrets here).
 */
function PlatformConfigurationList() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(
    () =>
      listPlatforms()
        .then((platforms) => setState({ status: "loaded", platforms }))
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  function retry() {
    setState({ status: "loading" });
    void load();
  }

  if (state.status === "loading") {
    return <Skeleton lines={6} label="Loading platform integrations…" />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        title="Couldn't load the platform integrations"
        message={state.message}
        onRetry={retry}
      />
    );
  }
  return (
    <ul className="ap-platform-list" aria-label="Platform integrations">
      {state.platforms.map((platform) => (
        <li key={platform.platform} className="ap-platform-row">
          <span className="ap-platform-row__name">{platform.label}</span>
          <StatusBadge platform={platform.status} />
          {platform.message && platform.status !== "configured" && (
            <p className="ap-meta ap-platform-row__message">
              {platform.message}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export default PlatformConfigurationList;
