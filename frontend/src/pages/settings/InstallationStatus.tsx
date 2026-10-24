import { useCallback, useEffect, useState } from "react";
import { getSystemStatus } from "../../api.ts";
import type { CredentialStoreStatus, SystemStatus } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import Icon from "../../ui/Icon.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { toApiError } from "../../utils.ts";

/** What each non-working secure-storage state means (contracts/ui.md §3). */
const CREDENTIAL_STORE_PROBLEMS: Record<
  Exclude<CredentialStoreStatus, "available">,
  string
> = {
  locked:
    "Secure storage is locked. Unlock your keyring on this computer so scheduled posts can be published.",
  unavailable:
    "Secure storage is not available. Scheduled posts cannot be published.",
  // Never "working": it could not be checked without a prompt.
  unknown:
    "Secure storage could not be checked without asking you to unlock it. If scheduled posts fail, unlock your keyring on this computer.",
};

const HTTP_WARNING =
  "Access over your network is not encrypted (HTTP). Only enable it on your private home network. It protects against other devices and websites using AutoPublisher without the password, but not against someone who can intercept or control your network.";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; system: SystemStatus };

function problems(system: SystemStatus): string[] {
  const found: string[] = [];
  if (system.database.status !== "ok") {
    found.push("The database is not responding.");
  }
  const store = system.credential_store.status;
  if (store !== "available") {
    found.push(CREDENTIAL_STORE_PROBLEMS[store]);
  }
  return found;
}

/**
 * Read-only state of the installed app (GET /api/system/status): its health,
 * how other devices reach it and its port. Host settings change outside the UI
 * (configure + restart); scheduler and pause stay in Automatic publishing.
 */
function InstallationStatus() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(
    () =>
      getSystemStatus()
        .then((system) => setState({ status: "loaded", system }))
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "loading") {
    return <Skeleton lines={4} label="Loading this installation…" />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        title="Couldn't load this installation's status"
        message={state.message}
        onRetry={() => {
          setState({ status: "loading" });
          void load();
        }}
      />
    );
  }
  const { system } = state;
  const issues = problems(system);
  const deployment = system.deployment;

  return (
    <div className="ap-installation">
      {issues.length === 0 ? (
        <p className="ap-installation__health">
          <Icon name="check" /> Everything is working.
        </p>
      ) : (
        <ul className="ap-installation__problems" aria-label="Problems">
          {issues.map((issue) => (
            <li key={issue}>
              <Icon name="alert" /> {issue}
            </li>
          ))}
        </ul>
      )}

      {deployment && (
        <>
          <h3 className="ap-installation__heading">
            Access from other devices
          </h3>
          {deployment.lan_enabled ? (
            <>
              {deployment.addresses.length > 0 ? (
                <>
                  <p className="ap-installation__text">
                    Open AutoPublisher on your phone or another computer at:
                  </p>
                  <ul
                    className="ap-installation__addresses"
                    aria-label="Addresses"
                  >
                    {deployment.addresses.map((address) => (
                      <li key={address}>
                        <code>{address}</code>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="ap-installation__text">
                  Could not detect this computer&apos;s address. See the
                  deployment guide.
                </p>
              )}
              {deployment.suggested_names.length > 0 && (
                <p className="ap-meta ap-installation__text">
                  This name may work on your network:{" "}
                  {deployment.suggested_names.map((name, index) => (
                    <span key={name}>
                      {index > 0 && ", "}
                      <code>{name}</code>
                    </span>
                  ))}
                </p>
              )}
              <p className="ap-installation__warning" role="note">
                <Icon name="alert" /> {HTTP_WARNING}
              </p>
            </>
          ) : (
            <>
              <p className="ap-installation__text">
                Only this computer can open AutoPublisher. To use it from your
                phone, follow “Access from other devices” in the deployment
                guide.
              </p>
              <p className="ap-meta ap-installation__text">
                Access over your network, when enabled, is not encrypted (HTTP).
              </p>
            </>
          )}
          <p className="ap-installation__text">Port {deployment.port}</p>
          <p className="ap-meta ap-installation__text">
            These settings belong to this computer. To change them, follow “Host
            configuration” in the deployment guide and restart the service.
          </p>
        </>
      )}
    </div>
  );
}

export default InstallationStatus;
