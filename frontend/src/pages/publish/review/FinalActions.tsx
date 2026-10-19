import { useState } from "react";
import { useNavigate } from "react-router";
import { useAutosaveRegistry } from "../../../components/platform/autosave-registry.ts";
import Button from "../../../ui/Button.tsx";
import { Dialog } from "../../../ui/Dialog.tsx";
import PageActions from "../../../ui/PageActions.tsx";
import { ctaLabel, type RunKind } from "../final-action.ts";

interface FinalActionsProps {
  projectId: number;
  /** Drafts the CTA acts on. */
  count: number;
  when: RunKind;
  busy: boolean;
  onSubmit: () => void;
}

/**
 * One primary CTA (never disabled: a problem shows the error summary) and the
 * tertiary `Finish later`. Finish later writes nothing of its own: it waits
 * for pending saves and leaves for Posts → Drafts, or asks what to do with a
 * change that couldn't be saved.
 */
function FinalActions({
  projectId,
  count,
  when,
  busy,
  onSubmit,
}: FinalActionsProps) {
  const registry = useAutosaveRegistry();
  const navigate = useNavigate();
  const [unsaved, setUnsaved] = useState<number | null>(null);
  const [leaving, setLeaving] = useState(false);

  const leave = () =>
    void navigate(`/p/${projectId}/posts`, { state: { focus: "drafts" } });

  async function finishLater(retry = false) {
    setLeaving(true);
    const saved = registry
      ? await (retry ? registry.retryFailed() : registry.flushAll())
      : true;
    const failed = registry?.failedKeys().length ?? 0;
    setLeaving(false);
    if (saved && failed === 0) {
      setUnsaved(null);
      leave();
    } else {
      setUnsaved(Math.max(failed, 1));
    }
  }

  return (
    <>
      <PageActions
        label="Publish actions"
        sticky
        primary={
          <Button variant="primary" loading={busy} onClick={onSubmit}>
            {ctaLabel(when, count)}
          </Button>
        }
        secondary={
          <Button
            variant="ghost"
            loading={leaving}
            onClick={() => void finishLater()}
          >
            Finish later
          </Button>
        }
      />
      {unsaved !== null && (
        <Dialog
          open
          onOpenChange={(open) => !open && setUnsaved(null)}
          title={`Couldn't save ${unsaved} ${unsaved === 1 ? "change" : "changes"}`}
          description="Try again, or leave without them. Everything else is saved."
          footer={
            <>
              <Button
                variant="primary"
                loading={leaving}
                onClick={() => void finishLater(true)}
              >
                Retry
              </Button>
              <Button variant="danger" onClick={leave}>
                Discard and leave
              </Button>
            </>
          }
        >
          {null}
        </Dialog>
      )}
    </>
  );
}

export default FinalActions;
