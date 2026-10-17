import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { createAccount, listPlatforms } from "../../api.ts";
import type { PlatformAvailability, Project } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import { Sheet } from "../../ui/Dialog.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { toApiError } from "../../utils.ts";

interface AddAccountSheetProps {
  project: Project;
  /** Reloads health, accounts and the project overview. */
  onChanged: () => Promise<void>;
}

/**
 * accounts/new only chooses the platform. "Set up <Platform>" creates the
 * provisional account (no handle) and goes straight to its detail, where the
 * existing connection panel and "Discard setup" live: the account in the
 * backend, not this sheet, carries the flow (reload, Back and Forward work).
 */
function AddAccountSheet({ project, onChanged }: AddAccountSheetProps) {
  const navigate = useNavigate();
  const base = `/p/${project.id}/accounts`;
  const [platforms, setPlatforms] = useState<PlatformAvailability[] | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [choice, setChoice] = useState<PlatformAvailability | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPlatforms()
      .then(setPlatforms)
      .catch((caught: unknown) => setLoadError(toApiError(caught).message));
  }, []);

  async function setUp(platform: PlatformAvailability) {
    setCreating(true);
    setError(null);
    try {
      const account = await createAccount(project.id, {
        platform: platform.platform,
      });
      // The list must know the account before its detail opens.
      await onChanged();
      // Replace /new: Back from the account returns to the list, not to a
      // platform choice whose account already exists.
      void navigate(`${base}/${account.id}`, { replace: true });
    } catch (caught) {
      setError(toApiError(caught).message);
      setCreating(false);
    }
  }

  return (
    <Sheet
      open
      onOpenChange={(open) => !open && void navigate(base)}
      title="Add account"
    >
      {!project.is_active ? (
        <p>Reactivate this project to add accounts.</p>
      ) : loadError ? (
        <p className="error" role="alert">
          {loadError}
        </p>
      ) : platforms === null ? (
        <Skeleton lines={4} label="Loading platforms…" />
      ) : (
        <div className="ap-add-account">
          <fieldset className="ap-platform-choice" disabled={creating}>
            <legend>Choose a platform</legend>
            {platforms.map((platform) => {
              const soon = platform.status === "coming_soon";
              return (
                <label
                  key={platform.platform}
                  className={
                    soon
                      ? "ap-platform-option ap-platform-option--soon"
                      : "ap-platform-option"
                  }
                >
                  <input
                    type="radio"
                    name="platform"
                    value={platform.platform}
                    disabled={soon}
                    checked={choice?.platform === platform.platform}
                    onChange={() => {
                      setChoice(platform);
                      setError(null);
                    }}
                  />
                  <span className="ap-platform-option__name">
                    {platform.label}
                  </span>
                  {soon ? (
                    <Badge tone="neutral" icon="clock">
                      Coming soon
                    </Badge>
                  ) : (
                    platform.status !== "configured" && (
                      <StatusBadge platform={platform.status} />
                    )
                  )}
                </label>
              );
            })}
          </fieldset>
          {choice && (
            <SetUpStep platform={choice} creating={creating} onSetUp={setUp} />
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </Sheet>
  );
}

function SetUpStep({
  platform,
  creating,
  onSetUp,
}: {
  platform: PlatformAvailability;
  creating: boolean;
  onSetUp: (platform: PlatformAvailability) => void;
}) {
  if (!platform.can_connect) {
    return (
      <div className="ap-add-account__step">
        <p>
          <strong>AutoPublisher isn't set up for {platform.label} yet.</strong>
        </p>
        {platform.message && <p className="ap-meta">{platform.message}</p>}
        <Button as="link" to="/settings" variant="primary">
          Open Settings
        </Button>
      </div>
    );
  }
  return (
    <div className="ap-add-account__step">
      {platform.message && <p className="ap-meta">{platform.message}</p>}
      <Button
        variant="primary"
        loading={creating}
        onClick={() => onSetUp(platform)}
      >
        Set up {platform.label}
      </Button>
    </div>
  );
}

export default AddAccountSheet;
