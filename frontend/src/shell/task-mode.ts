import { useMatches } from "react-router";

/** What a route can declare in its `handle` for the shell. */
export interface ShellHandle {
  /**
   * A focused task (e.g. Publish): phones hide the bottom navigation and the
   * project layout leaves out its header, status strip and Get started.
   */
  taskMode?: boolean;
}

export function useTaskMode(): boolean {
  return useMatches().some(
    (match) => (match.handle as ShellHandle | undefined)?.taskMode === true,
  );
}
