import { useCallback, useEffect, useState } from "react";
import { Outlet, useMatch, useParams } from "react-router";
import { ApiError, getOverview, getProject } from "../api.ts";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import { useReloadProjects } from "../shell/projects-reload.ts";
import { useTaskMode } from "../shell/task-mode.ts";
import type { Overview, Project } from "../types.ts";
import {
  clearLastProjectId,
  getLastProjectId,
  setLastProjectId,
} from "../ui-preferences.ts";
import { toApiError } from "../utils.ts";
import type { ProjectContext } from "./project-context.ts";
import OnboardingChecklist from "./project/OnboardingChecklist.tsx";
import ProjectHeader from "./project/ProjectHeader.tsx";
import ProjectStatusStrip from "./project/ProjectStatusStrip.tsx";
import "./project/project.css";

/** Layout of /p/:projectId: loads the project and hands it to its pages. */
function ProjectLayout() {
  const projectId = parseId(useParams().projectId);
  if (projectId === null) {
    return <NotFound />;
  }
  // A different project is a different layout: nothing of the previous one is kept.
  return <LoadedProject key={projectId} projectId={projectId} />;
}

type LoadState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error"; message: string }
  | { status: "loaded"; project: Project };

function LoadedProject({ projectId }: { projectId: number }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewVersion, setOverviewVersion] = useState(0);
  const reloadProjects = useReloadProjects();
  const section = useMatch("/p/:projectId/:section/*")?.params.section;
  const taskMode = useTaskMode();

  const reloadProject = useCallback(
    () =>
      getProject(projectId)
        .then((project) => {
          setLastProjectId(project.id);
          setState({ status: "loaded", project });
        })
        .catch((caught: unknown) => {
          if (caught instanceof ApiError && caught.status === 404) {
            if (getLastProjectId() === projectId) {
              clearLastProjectId();
            }
            setState({ status: "missing" });
          } else {
            setState({ status: "error", message: toApiError(caught).message });
          }
        }),
    [projectId],
  );
  const reloadOverview = useCallback(
    () => setOverviewVersion((value) => value + 1),
    [],
  );

  useEffect(() => {
    void reloadProject();
  }, [reloadProject]);

  // One overview request shared by the strip, the checklist and the pages;
  // loaded again when the section changes or a page reports a change.
  useEffect(() => {
    let active = true;
    getOverview(projectId)
      .then((loaded) => active && setOverview(loaded))
      .catch(() => active && setOverview(null));
    return () => {
      active = false;
    };
  }, [projectId, section, overviewVersion]);

  if (state.status === "loading") {
    return (
      <p className="muted" aria-busy="true">
        Loading project…
      </p>
    );
  }
  if (state.status === "missing") {
    return <NotFound />;
  }
  if (state.status === "error") {
    return (
      <p className="error" role="alert">
        {state.message}
      </p>
    );
  }

  async function handleProjectChanged() {
    await reloadProject();
    reloadOverview();
    reloadProjects();
  }

  const summary = overview?.projects[0] ?? null;
  const context: ProjectContext = {
    project: state.project,
    reloadProject,
    overview,
    reloadOverview,
  };
  return (
    <>
      {/* A task (Publish) shows only itself: no project header, strip or
          Get started above it. */}
      {!taskMode && (
        <ProjectHeader
          project={state.project}
          onChanged={handleProjectChanged}
        />
      )}
      {!taskMode && overview && summary && (
        <ProjectStatusStrip
          projectId={projectId}
          summary={summary}
          automation={overview.automation}
        />
      )}
      {!taskMode && summary && !summary.onboarding.complete && (
        <OnboardingChecklist
          projectId={projectId}
          onboarding={summary.onboarding}
        />
      )}
      <Outlet context={context} />
    </>
  );
}

export default ProjectLayout;
