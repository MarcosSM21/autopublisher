import { useCallback, useState } from "react";
import type { PostDisplayState } from "../types.ts";

interface PublishedEmphasisOptions {
  /**
   * Publish Results only (the fast-path): a Post of the current action whose
   * badge mounts already Published. Nothing else passes it.
   */
  initiallyEmphasized?: boolean;
}

/**
 * Whether a Post's badge shows the one-time Published emphasis
 * (contracts/ui.md §3). The state it mounts with is only the baseline, never a
 * transition; afterwards only `publishing` → `published` seen by this same
 * instance emphasises. Any other change, or `onEmphasisEnd`, clears it. Derived
 * during render (like `Flash`), compared by value, never persisted.
 */
export function usePublishedEmphasis(
  displayState: PostDisplayState | null,
  options: PublishedEmphasisOptions = {},
) {
  const [seen, setSeen] = useState(() => ({
    state: displayState,
    emphasis:
      options.initiallyEmphasized === true && displayState === "published",
  }));
  let current = seen;
  if (displayState !== seen.state) {
    current = {
      state: displayState,
      emphasis: seen.state === "publishing" && displayState === "published",
    };
    setSeen(current);
  }
  const onEmphasisEnd = useCallback(
    () =>
      setSeen((previous) =>
        previous.emphasis ? { ...previous, emphasis: false } : previous,
      ),
    [],
  );
  return { emphasis: current.emphasis, onEmphasisEnd };
}
