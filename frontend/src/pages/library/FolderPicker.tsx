import { useState } from "react";
import type { LibraryFolder } from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import { Dialog, Sheet } from "../../ui/Dialog.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { toApiError } from "../../utils.ts";
import { folderTreeOrder } from "./library-folders.ts";

const UNSORTED = "unsorted";

interface FolderPickerProps {
  title: string;
  folders: readonly LibraryFolder[];
  /** Where the Media already are (null = Unsorted); undefined if mixed. */
  current: number | null | undefined;
  /** Moves to the folder (null = Unsorted); a rejection is shown inline. */
  onMove: (folderId: number | null) => Promise<void>;
  /** The move found missing media or a missing folder: reload the view. */
  onStale: () => void;
  onClose: () => void;
}

/**
 * Where to move Media: Unsorted first, then the folder tree indented by depth,
 * one tappable row per destination. All media is a view, never a destination.
 * A sheet on phones, a dialog from md. Mounted while open.
 */
function FolderPicker({
  title,
  folders,
  current,
  onMove,
  onStale,
  onClose,
}: FolderPickerProps) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const Surface = isMedium ? Dialog : Sheet;
  const [choice, setChoice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const currentValue =
    current === undefined
      ? null
      : current === null
        ? UNSORTED
        : String(current);
  const destinations = [
    { value: UNSORTED, label: "Unsorted", depth: 1 },
    ...folderTreeOrder(folders).map((folder) => ({
      value: String(folder.id),
      label: folder.name,
      depth: folder.depth,
    })),
  ];

  async function handleMove() {
    if (choice === null) {
      return;
    }
    setMoving(true);
    setError(null);
    try {
      await onMove(choice === UNSORTED ? null : Number(choice));
    } catch (caught) {
      const apiError = toApiError(caught);
      if (apiError.status === 404) {
        setError(
          "Some of the media or the folder no longer exist. Nothing was moved.",
        );
        onStale();
      } else {
        setError(apiError.message);
      }
      setMoving(false);
    }
  }

  return (
    <Surface
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
      title={title}
      footer={
        <>
          <Button
            variant="primary"
            loading={moving}
            disabled={choice === null || choice === currentValue}
            onClick={() => void handleMove()}
          >
            Move here
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <fieldset className="ap-folder-picker">
        <legend className="ap-visually-hidden">Destination</legend>
        {destinations.map((destination) => (
          <label
            key={destination.value}
            className="ap-folder-picker__row"
            data-depth={destination.depth}
          >
            <input
              type="radio"
              name="destination"
              value={destination.value}
              checked={choice === destination.value}
              onChange={() => setChoice(destination.value)}
            />
            <span className="ap-folder-picker__name">{destination.label}</span>
            {destination.value === currentValue && (
              <span className="ap-meta">Current</span>
            )}
          </label>
        ))}
      </fieldset>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Surface>
  );
}

export default FolderPicker;
