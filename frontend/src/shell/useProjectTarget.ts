import { useCallback, useEffect, useState } from "react";
import { useLocation, useMatch } from "react-router";
import { listProjects } from "../api.ts";
import { parseId } from "../route-params.ts";
import type { Project } from "../types.ts";
import { getLastProjectId } from "../ui-preferences.ts";

export const PROJECT_SECTIONS = [
  "library",
  "posts",
  "accounts",
  "analytics",
] as const;
export type ProjectSection = (typeof PROJECT_SECTIONS)[number];

export interface ProjectTarget {
  /** null while loading; empty when there are no projects (or they failed to load). */
  projects: Project[] | null;
  loadFailed: boolean;
  /** Project the project destinations open; null when there is none. */
  projectId: number | null;
  /** Whether projectId comes from the URL (the user is inside a project). */
  inProject: boolean;
  /** Current project section, if the URL is one of them (detail ids dropped). */
  section: ProjectSection | null;
  /** Loads the project list again (after a rename or (de)activation). */
  reload: () => void;
}

/**
 * Project for the section links outside a project: the last one opened if it
 * still exists, otherwise the first active one (or the first one).
 */
function defaultProjectId(projects: Project[]): number | null {
  const lastId = getLastProjectId();
  if (lastId !== null && projects.some((project) => project.id === lastId)) {
    return lastId;
  }
  const first = projects.find((project) => project.is_active) ?? projects[0];
  return first?.id ?? null;
}

function asSection(value: string | undefined): ProjectSection | null {
  return PROJECT_SECTIONS.find((section) => section === value) ?? null;
}

/**
 * The single resolution of "which project" for the shell: the project in the
 * URL, or (in global context: Home, Settings) the last valid project, the first
 * active one or the first one; null without projects. The URL stays the only
 * navigation state: nothing here is written back.
 */
export function useProjectTarget(): ProjectTarget {
  const projectMatch = useMatch("/p/:projectId/*");
  const sectionMatch = useMatch("/p/:projectId/:section/*");
  const { pathname } = useLocation();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);

  const urlProjectId = projectMatch
    ? parseId(projectMatch.params.projectId)
    : null;
  const inProject = projectMatch !== null;
  // Reload when entering another project, and on every global navigation:
  // projects may have been created or removed meanwhile (e.g. from Home).
  const reloadKey = inProject ? `p${projectMatch.params.projectId}` : pathname;

  useEffect(() => {
    let active = true;
    listProjects()
      .then((loaded) => {
        if (active) {
          setProjects(loaded);
          setLoadFailed(false);
        }
      })
      .catch(() => {
        if (active) {
          setProjects([]);
          setLoadFailed(true);
        }
      });
    return () => {
      active = false;
    };
  }, [reloadKey, version]);

  return {
    projects,
    loadFailed,
    projectId: inProject
      ? urlProjectId
      : projects
        ? defaultProjectId(projects)
        : null,
    inProject,
    section: asSection(sectionMatch?.params.section),
    reload,
  };
}
