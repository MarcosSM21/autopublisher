import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { MEDIA_LG_UP, MEDIA_MD_UP, MEDIA_XL_UP } from "./breakpoints.ts";
import Button from "./Button.tsx";
import { Drawer } from "./Dialog.tsx";
import IconButton from "./IconButton.tsx";
import PageActions from "./PageActions.tsx";
import { useMediaQuery } from "./useMediaQuery.ts";

interface DetailSurfaceProps {
  /** Heading and accessible name of the detail. */
  title: string;
  /** Where closing (or Back) navigates: the list the detail belongs to. */
  parentPath: string;
  /**
   * From which breakpoint the detail sits next to the list as a side panel.
   * Below it, it is a drawer (`md`+) or a page (`sm`). Pages whose list needs
   * the width choose `xl` (Library) or `never` (the Calendar week: always a
   * drawer from `md`).
   */
  panelFrom?: "lg" | "xl" | "never";
  /** The detail's main actions, kept visible at the bottom of the surface. */
  actions?: ReactNode;
  /**
   * The list's page title (e.g. "Posts"), for details whose content has its own
   * section headings. As a full page (`sm`) the list and its h1 are hidden: the
   * page keeps that h1 (visually hidden) and the detail's title becomes an h2,
   * like in the panel and the drawer, so its h3 sections never skip a level.
   */
  sectionTitle?: string;
  /**
   * The drawer's focus target on close (see `Modal.returnFocus`), e.g. when
   * the element that opened it is gone. The panel and the page ignore it.
   */
  returnFocus?: () => HTMLElement | null;
  children: ReactNode;
}

/**
 * The detail of an item in a list, by viewport: side panel next to the list (not
 * modal), drawer (modal) or full page with "Back". Closing always navigates to
 * the parent URL (never `history.back()`), so deep links work.
 *
 * The content is rendered once, through a portal into a node that each surface
 * only hosts: crossing a breakpoint moves that node instead of remounting the
 * content, so its state (e.g. a connection attempt being polled) survives.
 */
function DetailSurface({
  title,
  parentPath,
  panelFrom = "lg",
  actions,
  sectionTitle,
  returnFocus,
  children,
}: DetailSurfaceProps) {
  const [contentNode] = useState(() => document.createElement("div"));
  return (
    <>
      {createPortal(children, contentNode)}
      <Surface
        title={title}
        parentPath={parentPath}
        panelFrom={panelFrom}
        actions={actions}
        sectionTitle={sectionTitle}
        returnFocus={returnFocus}
      >
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

/**
 * Moves focus to the heading when the detail was opened from the page (a link
 * or button had focus), not on a reload or a deep link, where focus stays at
 * the start of the document. Drawers get their focus from the dialog itself.
 */
function useFocusOnOpen() {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body) {
      heading.current?.focus();
    }
  }, []);
  return heading;
}

function Surface({
  title,
  parentPath,
  panelFrom,
  actions,
  sectionTitle,
  returnFocus,
  children,
}: DetailSurfaceProps) {
  const navigate = useNavigate();
  const titleId = useId();
  const isLarge = useMediaQuery(MEDIA_LG_UP);
  const isExtraLarge = useMediaQuery(MEDIA_XL_UP);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const close = () => void navigate(parentPath);
  const panel =
    panelFrom === "never" ? false : panelFrom === "xl" ? isExtraLarge : isLarge;

  if (panel) {
    return (
      <PanelSurface title={title} onClose={close} actions={actions}>
        {children}
      </PanelSurface>
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
        footer={actions}
        returnFocus={returnFocus}
      >
        {children}
      </Drawer>
    );
  }
  return (
    <PageSurface
      title={title}
      titleId={titleId}
      onClose={close}
      actions={actions}
      sectionTitle={sectionTitle}
    >
      {children}
    </PageSurface>
  );
}

interface SurfaceProps {
  title: string;
  onClose: () => void;
  actions?: ReactNode;
  children: ReactNode;
}

function PanelSurface({ title, onClose, actions, children }: SurfaceProps) {
  const heading = useFocusOnOpen();
  return (
    <aside className="ap-detail-panel" aria-label={title}>
      <header className="ap-detail-panel__header">
        <h2 ref={heading} tabIndex={-1} className="ap-detail-panel__title">
          {title}
        </h2>
        <IconButton icon="close" label="Close" onClick={onClose} />
      </header>
      <div className="ap-detail-panel__body">{children}</div>
      {actions && (
        <footer className="ap-detail-panel__footer">{actions}</footer>
      )}
    </aside>
  );
}

function PageSurface({
  title,
  titleId,
  onClose,
  actions,
  sectionTitle,
  children,
}: SurfaceProps & { titleId: string; sectionTitle?: string }) {
  const heading = useFocusOnOpen();
  const Title = sectionTitle === undefined ? "h1" : "h2";
  return (
    <section className="ap-detail-page" aria-labelledby={titleId}>
      {sectionTitle !== undefined && (
        <h1 className="ap-visually-hidden">{sectionTitle}</h1>
      )}
      <Button variant="ghost" icon="back" onClick={onClose}>
        Back
      </Button>
      <Title
        ref={heading}
        id={titleId}
        tabIndex={-1}
        className="ap-detail-page__title"
      >
        {title}
      </Title>
      {children}
      {actions && (
        <PageActions label={`${title} actions`} primary={actions} sticky />
      )}
    </section>
  );
}

export default DetailSurface;
