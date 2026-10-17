import { useOutletContext } from "react-router";
import type { Overview, Project } from "../types.ts";

/** What ProjectLayout hands to the pages of a project. */
export interface ProjectContext {
  project: Project;
  reloadProject: () => Promise<void>;
  /** The project's overview (null until loaded or if it failed), loaded once. */
  overview: Overview | null;
  /** Reloads the overview after a change that affects it (import, post…). */
  reloadOverview: () => void;
}

export function useProject(): ProjectContext {
  return useOutletContext<ProjectContext>();
}
