import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import MediaPreview from "../../components/MediaPreview.tsx";
import type { Content } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import Icon from "../../ui/Icon.tsx";
import { formatDuration } from "../../utils.ts";
import { usageIndicator } from "./usage-indicator.ts";

interface MediaCardProps {
  content: Content;
  to: string;
  selected: boolean;
  /** The Media's folder ("Unsorted" or a name), where it isn't obvious. */
  folderLabel?: string;
  /** In Select mode the card is a checkbox instead of a link. */
  checked?: boolean;
  onToggle?: () => void;
  /** The card's "Media actions" menu (outside Select mode). */
  onMove?: () => void;
  onDelete?: () => void;
}

/**
 * One Media in the grid, as a single link: preview, duration (videos), title or
 * file name, its folder in All media and one usage indicator. No technical
 * data. Beside the link, a tap-to-open "Media actions" menu (Move, Delete
 * media). In Select mode the whole card toggles a visible checkbox.
 */
function MediaCard({
  content,
  to,
  selected,
  folderLabel,
  checked,
  onToggle,
  onMove,
  onDelete,
}: MediaCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const itemRef = useRef<HTMLLIElement>(null);
  // Closing the menu hides the item that was clicked: the dialog it opens
  // remembers the card's "Media actions" button instead, and gives focus back
  // to it.
  function runFromMenu(action: () => void) {
    setMenuOpen(false);
    itemRef.current
      ?.querySelector<HTMLElement>(".ap-media-card__actions > button")
      ?.focus();
    action();
  }
  const indicator = usageIndicator(content.usage);
  const name = content.title ?? content.original_filename;
  const body: ReactNode = (
    <>
      <span className="ap-media-card__preview">
        <MediaPreview content={content} />
        {content.media_type === "video" &&
          content.duration_seconds !== null && (
            <span className="ap-media-card__duration ap-tabular">
              <span className="ap-visually-hidden">Duration </span>
              {formatDuration(content.duration_seconds)}
            </span>
          )}
      </span>
      <span className="ap-media-card__title">{name}</span>
      {folderLabel !== undefined && (
        <span className="ap-meta ap-media-card__folder">
          <span className="ap-visually-hidden">Folder: </span>
          {folderLabel}
        </span>
      )}
      {indicator && (
        <Badge tone={indicator.tone} icon={indicator.icon}>
          {indicator.label}
        </Badge>
      )}
    </>
  );

  if (onToggle) {
    return (
      <li>
        <label
          className={
            checked
              ? "ap-media-card ap-media-card--checkable ap-media-card--checked"
              : "ap-media-card ap-media-card--checkable"
          }
        >
          <input
            type="checkbox"
            className="ap-media-card__check"
            checked={checked ?? false}
            onChange={onToggle}
          />
          {body}
        </label>
      </li>
    );
  }
  const menu = (onMove || onDelete) && (
    <Disclosure
      label={
        <>
          <Icon name="more" />
          <span className="ap-visually-hidden">Media actions: {name}</span>
        </>
      }
      className="ap-menu ap-media-card__actions"
      open={menuOpen}
      onOpenChange={setMenuOpen}
    >
      {onMove && <Button onClick={() => runFromMenu(onMove)}>Move</Button>}
      {onDelete && (
        <Button
          className="ap-delete-entry"
          onClick={() => runFromMenu(onDelete)}
        >
          Delete media
        </Button>
      )}
    </Disclosure>
  );
  return (
    <li ref={itemRef} className={menu ? "ap-media-grid__item" : undefined}>
      <Link
        to={to}
        className={
          selected ? "ap-media-card ap-media-card--selected" : "ap-media-card"
        }
        aria-current={selected ? "true" : undefined}
        data-detail-id={content.id}
      >
        {body}
      </Link>
      {menu}
    </li>
  );
}

export default MediaCard;
