import { useCallback, useId, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { MEDIA_LG_UP, MEDIA_MD_UP } from "./breakpoints.ts";
import Button from "./Button.tsx";
import { Drawer } from "./Dialog.tsx";
import IconButton from "./IconButton.tsx";
import { useMediaQuery } from "./useMediaQuery.ts";

interface DetailSurfaceProps {
  /** Heading and accessible name of the detail. */
  title: string;
  /** Where closing (or Back) navigates: the list the detail belongs to. */
  parentPath: string;
  children: ReactNode;
}

/**
 * The detail of an item in a list, by viewport: `lg` side panel next to the list
 * (not modal), `md` drawer (modal), `sm` full page with "Back". Closing always
 * navigates to the parent URL (never `history.back()`), so deep links work.
 *
 * The content is rendered once, through a portal into a node that each surface
 * only hosts: crossing a breakpoint moves that node instead of remounting the
 * content, so its state (e.g. a connection attempt being polled) survives.
 */
function DetailSurface({ title, parentPath, children }: DetailSurfaceProps) {
  const [contentNode] = useState(() => document.createElement("div"));
  return (
    <>
      {createPortal(children, contentNode)}
      <Surface title={title} parentPath={parentPath}>
        <ContentHost node={contentNode} />
      </Surface>
    </>
  );
}

/** Attaches the persistent content node wherever the current surface puts it. */
function ContentHost({ node }: { node: HTMLElement }) {
  const attach = useCallback(
    (host: HTMLDivElement | null) => {
      if (host) {
        host.appendChild(node);
      }
    },
    [node],
  );
  return <div ref={attach} className="ap-detail-content" />;
}

function Surface({ title, parentPath, children }: DetailSurfaceProps) {
  const navigate = useNavigate();
  const titleId = useId();
  const isLarge = useMediaQuery(MEDIA_LG_UP);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const close = () => void navigate(parentPath);

  if (isLarge) {
    return (
      <aside className="ap-detail-panel" aria-label={title}>
        <header className="ap-detail-panel__header">
          <h2 className="ap-detail-panel__title">{title}</h2>
          <IconButton icon="close" label="Close" onClick={close} />
        </header>
        {children}
      </aside>
    );
  }
  if (isMedium) {
    return (
      <Drawer
        open
        onOpenChange={(open) => {
          if (!open) {
            close();
          }
        }}
        title={title}
      >
        {children}
      </Drawer>
    );
  }
  return (
    <section className="ap-detail-page" aria-labelledby={titleId}>
      <Button variant="ghost" icon="back" onClick={close}>
        Back
      </Button>
      <h1 id={titleId} className="ap-detail-page__title">
        {title}
      </h1>
      {children}
    </section>
  );
}

export default DetailSurface;
