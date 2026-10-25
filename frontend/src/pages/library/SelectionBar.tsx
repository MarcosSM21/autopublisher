import Button from "../../ui/Button.tsx";

interface SelectionBarProps {
  count: number;
  onMove: () => void;
  onDelete: () => void;
  onCancel: () => void;
}

/**
 * Select mode's bar, fixed to the bottom of the view (above the phone's
 * navigation): the count, the bulk actions Move and Delete, and Cancel. Move
 * stays the primary one; Delete is a secondary, destructive-text button.
 */
function SelectionBar({
  count,
  onMove,
  onDelete,
  onCancel,
}: SelectionBarProps) {
  return (
    <div role="region" aria-label="Selection" className="ap-selection-bar">
      <p className="ap-selection-bar__count" aria-live="polite">
        {count} selected
      </p>
      <Button variant="primary" disabled={count === 0} onClick={onMove}>
        Move
      </Button>
      <Button
        className="ap-delete-entry"
        disabled={count === 0}
        onClick={onDelete}
      >
        Delete
      </Button>
      <Button onClick={onCancel}>Cancel</Button>
    </div>
  );
}

export default SelectionBar;
