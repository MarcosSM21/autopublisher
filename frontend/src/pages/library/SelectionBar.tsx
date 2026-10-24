import Button from "../../ui/Button.tsx";

interface SelectionBarProps {
  count: number;
  onMove: () => void;
  onCancel: () => void;
}

/**
 * Select mode's bar, fixed to the bottom of the view (above the phone's
 * navigation): the count, Move (the only bulk action) and Cancel.
 */
function SelectionBar({ count, onMove, onCancel }: SelectionBarProps) {
  return (
    <div role="region" aria-label="Selection" className="ap-selection-bar">
      <p className="ap-selection-bar__count" aria-live="polite">
        {count} selected
      </p>
      <Button variant="primary" disabled={count === 0} onClick={onMove}>
        Move
      </Button>
      <Button onClick={onCancel}>Cancel</Button>
    </div>
  );
}

export default SelectionBar;
