import { useCallback, useEffect, useRef, useState } from "react";
import type { DeletionBlocker, DeletionPreview } from "../types.ts";
import { MEDIA_MD_UP } from "../ui/breakpoints.ts";
import Button from "../ui/Button.tsx";
import { Dialog, Sheet } from "../ui/Dialog.tsx";
import ErrorState from "../ui/ErrorState.tsx";
import Skeleton from "../ui/Skeleton.tsx";
import { useMediaQuery } from "../ui/useMediaQuery.ts";
import { toApiError } from "../utils.ts";
import "./delete-confirm-dialog.css";

export const DELETION_CHANGED_MESSAGE = "Something changed. Review it again.";
const BUSY_CODES: readonly string[] = [
  "post_in_progress",
  "metadata_removal_in_progress",
];

interface DeleteConfirmDialogProps {
  /** "Delete post?", "Delete media?"… */
  title: string;
  /** Optional context under the title (e.g. Discard setup). */
  description?: string;
  /** The destructive button; "Delete" unless the flow names it otherwise. */
  confirmLabel?: string;
  loadPreview: () => Promise<DeletionPreview>;
  /** The DELETE, with the token of the preview the user is looking at. */
  remove: (confirmation: string) => Promise<void>;
  /** Deleted, or already gone (404): the caller reloads and navigates. */
  onDeleted: () => void;
  onClose: () => void;
}

type PreviewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; preview: DeletionPreview };

/** A server, network or unknown failure: no technical detail for the user. */
function failureText(status: number, message: string): string {
  return status === 0 || status >= 500
    ? "Couldn't delete it. Try again."
    : message;
}

/**
 * The one confirmation of every delete (contracts/ui.md §1): the backend's
 * summary of what disappears, then Delete with that preview's token. It never
 * asks to type anything. A changed scope (`409 deletion_changed`) shows the new
 * preview and waits for another explicit Delete; a blocker only offers Close.
 */
function DeleteConfirmDialog({
  title,
  description,
  confirmLabel = "Delete",
  loadPreview,
  remove,
  onDeleted,
  onClose,
}: DeleteConfirmDialogProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const Surface = isMedium ? Dialog : Sheet;
  const [state, setState] = useState<PreviewState>({ status: "loading" });
  const [changed, setChanged] = useState(false);
  // A 409 busy answered by the DELETE: shown like the preview's blocker.
  const [busyBlocker, setBusyBlocker] = useState<DeletionBlocker | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // A ref, not only state: a double click never sends two DELETEs.
  const sending = useRef(false);
  const latest = useRef({ loadPreview, onDeleted });
  useEffect(() => {
    latest.current = { loadPreview, onDeleted };
  });

  const load = useCallback(async () => {
    try {
      const preview = await latest.current.loadPreview();
      setState({ status: "loaded", preview });
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.status === 404) {
        // Deleted meanwhile (another tab): nothing left to confirm.
        latest.current.onDeleted();
        return;
      }
      setState({
        status: "error",
        message: failureText(apiError.status, apiError.message),
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function confirm(preview: DeletionPreview) {
    if (sending.current) {
      return;
    }
    sending.current = true;
    setDeleting(true);
    setError(null);
    try {
      await remove(preview.confirmation);
      onDeleted();
      return;
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.status === 404) {
        onDeleted();
        return;
      }
      if (apiError.code === "deletion_changed") {
        // Never delete the new scope on its own: show it and wait.
        setChanged(true);
        setState({ status: "loading" });
        await load();
      } else if (BUSY_CODES.includes(apiError.code)) {
        setBusyBlocker({
          code: apiError.code as DeletionBlocker["code"],
          message: apiError.message,
        });
      } else {
        setError(failureText(apiError.status, apiError.message));
      }
    }
    sending.current = false;
    setDeleting(false);
  }

  const preview = state.status === "loaded" ? state.preview : null;
  const blocker = busyBlocker ?? preview?.blocker ?? null;
  const canDelete = preview !== null && blocker === null;

  return (
    <Surface
      open
      onOpenChange={(open) => !open && onClose()}
      title={title}
      description={description}
      footer={
        canDelete ? (
          <div className="ap-delete-dialog__footer">
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => void confirm(preview)}
            >
              {confirmLabel}
            </Button>
            <Button onClick={onClose} disabled={deleting}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="ap-delete-dialog__footer">
            <Button onClick={onClose}>Close</Button>
          </div>
        )
      }
    >
      <div className="ap-delete-dialog">
        {changed && (
          <p className="ap-delete-dialog__changed" role="alert">
            {DELETION_CHANGED_MESSAGE}
          </p>
        )}
        {state.status === "loading" && (
          <Skeleton lines={2} label="Checking what will be deleted…" />
        )}
        {state.status === "error" && (
          <ErrorState
            title="Couldn't check what will be deleted"
            message={state.message}
            onRetry={() => {
              setState({ status: "loading" });
              void load();
            }}
          />
        )}
        {preview && (
          <>
            <p className="ap-delete-dialog__name">{preview.name}</p>
            {blocker ? (
              <p className="ap-delete-dialog__blocker">{blocker.message}</p>
            ) : (
              preview.summary.map((line) => <p key={line}>{line}</p>)
            )}
          </>
        )}
        {error && (
          <p className="ap-field__error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Surface>
  );
}

export default DeleteConfirmDialog;
