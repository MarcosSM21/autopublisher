import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from "react";
import { Link } from "react-router";
import Icon from "../../ui/Icon.tsx";

/**
 * `New post`: Publish media… (starts from the Library) or a Text post. A
 * button that shows two links. Choosing one, clicking outside or moving the
 * focus away closes it; Escape closes it and returns the focus to the button.
 */
function NewPostMenu({ projectId }: { projectId: number }) {
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
      button.current?.focus();
    }
  }

  function onBlur(event: FocusEvent) {
    const next = event.relatedTarget;
    if (next instanceof Node && !root.current?.contains(next)) {
      setOpen(false);
    }
  }

  const close = () => setOpen(false);
  return (
    <div
      ref={root}
      className="ap-new-post"
      onKeyDown={onKeyDown}
      onBlur={onBlur}
    >
      <button
        ref={button}
        type="button"
        className="ap-button ap-button--primary"
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen(!open)}
      >
        <Icon name="plus" />
        <span>New post</span>
      </button>
      <ul id={regionId} className="ap-new-post__menu" hidden={!open}>
        <li>
          <Link
            className="ap-new-post__item"
            to={`/p/${projectId}/library`}
            onClick={close}
          >
            Publish media…
            <span className="ap-meta">Choose a Media in the Library</span>
          </Link>
        </li>
        <li>
          <Link
            className="ap-new-post__item"
            to={`/p/${projectId}/posts/new`}
            onClick={close}
          >
            Text post
            <span className="ap-meta">A post without media</span>
          </Link>
        </li>
      </ul>
    </div>
  );
}

export default NewPostMenu;
