import type { MouseEvent } from "react";
import { Outlet } from "react-router";
import { MEDIA_LG_UP, MEDIA_MD_UP } from "../ui/breakpoints.ts";
import { useMediaQuery } from "../ui/useMediaQuery.ts";
import PrimaryNav from "./PrimaryNav.tsx";
import { ProjectsReloadContext } from "./projects-reload.ts";
import ProjectSelector from "./ProjectSelector.tsx";
import TopBar from "./TopBar.tsx";
import { useProjectTarget } from "./useProjectTarget.ts";
import "./shell.css";

const MAIN_ID = "main-content";

/**
 * The single responsive shell. CSS lays out the navigation per breakpoint; JS
 * only decides where the project selector lives (sidebar on `lg`, TopBar on
 * `sm`/`md`) and whether "More" exists (`sm`), so no node is duplicated.
 */
function AppShell() {
  const target = useProjectTarget();
  const isLarge = useMediaQuery(MEDIA_LG_UP);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const selector = <ProjectSelector target={target} />;

  function skipToContent(event: MouseEvent<HTMLAnchorElement>) {
    // Focus the main region without a hash navigation in the router.
    event.preventDefault();
    const main = document.getElementById(MAIN_ID);
    main?.focus();
    main?.scrollIntoView();
  }

  return (
    <div className="ap-shell">
      <a className="ap-skip-link" href={`#${MAIN_ID}`} onClick={skipToContent}>
        Skip to content
      </a>
      {/* DOM order = keyboard order: TopBar, navigation, content. CSS grid
          areas (and the fixed bottom bar on phones) place them visually. */}
      {!isLarge && <TopBar projectSelector={selector} showMore={!isMedium} />}
      <PrimaryNav
        projectId={target.projectId}
        projectSelector={isLarge ? selector : undefined}
      />
      <main id={MAIN_ID} className="ap-shell__main" tabIndex={-1}>
        <ProjectsReloadContext.Provider value={target.reload}>
          <Outlet />
        </ProjectsReloadContext.Provider>
      </main>
    </div>
  );
}

export default AppShell;
