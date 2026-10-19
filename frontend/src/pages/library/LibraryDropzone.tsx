import Button from "../../ui/Button.tsx";
import EmptyState from "../../ui/EmptyState.tsx";

interface LibraryDropzoneProps {
  /** Drop works on this device (md+); otherwise only the picker is offered. */
  canDrop: boolean;
  dragging: boolean;
  /** Whether importing is the page's next step (see onboarding). */
  primary: boolean;
  disabledReason: string | null;
  busy: boolean;
  onChoose: () => void;
}

/**
 * The empty Library: a large drop zone with a single import action, which is
 * never the only way in on phones (it opens the file picker).
 */
function LibraryDropzone({
  canDrop,
  dragging,
  primary,
  disabledReason,
  busy,
  onChoose,
}: LibraryDropzoneProps) {
  return (
    <section
      aria-label="Import media"
      className={
        dragging
          ? "ap-library-dropzone ap-library-dropzone--active"
          : "ap-library-dropzone"
      }
    >
      <EmptyState
        title="Import your first media"
        description={
          disabledReason ??
          (canDrop
            ? "Drop images or videos here, or choose them from your device."
            : "Choose images or videos from your device.")
        }
        action={
          <Button
            variant={primary ? "primary" : "secondary"}
            icon="plus"
            disabled={disabledReason !== null || busy}
            onClick={onChoose}
          >
            Import media
          </Button>
        }
      />
    </section>
  );
}

export default LibraryDropzone;
