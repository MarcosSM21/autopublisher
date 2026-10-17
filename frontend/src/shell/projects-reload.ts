import { createContext, useContext } from "react";

/**
 * Lets a page tell the shell that the project list changed (rename, activate),
 * so the project selector refreshes without leaving the route.
 */
export const ProjectsReloadContext = createContext<() => void>(() => {});

export function useReloadProjects(): () => void {
  return useContext(ProjectsReloadContext);
}
