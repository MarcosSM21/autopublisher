import { useState, type DragEvent } from "react";

/** Whether a drag carries files (not text or a link from the page). */
function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/**
 * Drag and drop of files anywhere on the Library page. Only enabled from md
 * up: phones import with the file picker.
 */
export function usePageDrop(
  enabled: boolean,
  onFiles: (files: File[]) => void,
) {
  const [dragging, setDragging] = useState(false);
  if (!enabled) {
    return { dragging: false, handlers: {} };
  }
  return {
    dragging,
    handlers: {
      onDragEnter(event: DragEvent<HTMLElement>) {
        if (hasFiles(event)) {
          event.preventDefault();
          setDragging(true);
        }
      },
      onDragOver(event: DragEvent<HTMLElement>) {
        if (hasFiles(event)) {
          event.preventDefault();
        }
      },
      onDragLeave(event: DragEvent<HTMLElement>) {
        // Only when the pointer leaves the page, not when it crosses children.
        if (
          !(event.relatedTarget instanceof Node) ||
          !event.currentTarget.contains(event.relatedTarget)
        ) {
          setDragging(false);
        }
      },
      onDrop(event: DragEvent<HTMLElement>) {
        if (hasFiles(event)) {
          event.preventDefault();
          setDragging(false);
          onFiles(Array.from(event.dataTransfer.files));
        }
      },
    },
  };
}
