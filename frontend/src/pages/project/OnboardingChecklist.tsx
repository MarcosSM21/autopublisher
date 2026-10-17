import { useEffect, useState } from "react";
import { useMatch } from "react-router";
import { listContents } from "../../api.ts";
import type { ProjectSummary } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import Icon from "../../ui/Icon.tsx";

interface OnboardingChecklistProps {
  projectId: number;
  /** Derived by the backend from the real state; nothing is stored. */
  onboarding: ProjectSummary["onboarding"];
}

/**
 * The three first steps (research §13). Only the next step has an action; the
 * layout hides the checklist once `complete`.
 */
function OnboardingChecklist({
  projectId,
  onboarding,
}: OnboardingChecklistProps) {
  const base = `/p/${projectId}`;
  const publishNext =
    onboarding.account_ready &&
    onboarding.media_imported &&
    !onboarding.post_created;
  const firstUnused = useFirstUnusedMedia(projectId, publishNext);
  // On the page whose empty state already offers the same action, the step
  // keeps its text but not a second, competing button.
  const section = useMatch("/p/:projectId/:section/*")?.params.section;
  const steps = [
    {
      done: onboarding.account_ready,
      label: "An account ready to publish",
      action: { label: "Connect an account", to: `${base}/accounts/new` },
      section: "accounts",
    },
    {
      done: onboarding.media_imported,
      label: "Media in the Library",
      action: { label: "Import media", to: `${base}/library` },
      section: "library",
    },
    {
      done: onboarding.post_created,
      label: "A first post",
      action: {
        label: "Publish…",
        to:
          firstUnused === null
            ? `${base}/library`
            : `${base}/library/${firstUnused}`,
      },
      section: null,
    },
  ];
  const next = steps.findIndex((step) => !step.done);

  return (
    <section className="ap-onboarding" aria-labelledby="onboarding-title">
      <h2 id="onboarding-title" className="ap-onboarding__title">
        Get started
      </h2>
      <ol className="ap-onboarding__steps">
        {steps.map((step, index) => (
          <li
            key={step.label}
            className={
              step.done
                ? "ap-onboarding__step ap-onboarding__step--done"
                : "ap-onboarding__step"
            }
            aria-current={index === next ? "step" : undefined}
          >
            <Icon name={step.done ? "check" : "circle"} />
            <span className="ap-onboarding__label">
              {step.label}
              <span className="ap-visually-hidden">
                {step.done ? " (done)" : " (to do)"}
              </span>
            </span>
            {index === next && step.section !== section && (
              <Button as="link" variant="primary" to={step.action.to}>
                {step.action.label}
              </Button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The first media no post uses yet, only when "Publish…" is the next step. */
function useFirstUnusedMedia(
  projectId: number,
  enabled: boolean,
): number | null {
  const [mediaId, setMediaId] = useState<number | null>(null);
  useEffect(() => {
    if (!enabled) {
      return;
    }
    let active = true;
    listContents(projectId)
      .then((contents) => {
        const unused = contents.find((content) => !content.usage.used);
        if (active) {
          setMediaId(unused?.id ?? null);
        }
      })
      .catch(() => active && setMediaId(null));
    return () => {
      active = false;
    };
  }, [projectId, enabled]);
  return enabled ? mediaId : null;
}

export default OnboardingChecklist;
