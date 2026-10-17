import { useCallback, useSyncExternalStore } from "react";

function hasMatchMedia(): boolean {
  return (
    typeof window !== "undefined" && typeof window.matchMedia === "function"
  );
}

/**
 * Whether a media query matches, kept in sync with the viewport. Without
 * `matchMedia` (jsdom, old browsers) it answers false: the mobile-first layout.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      if (!hasMatchMedia()) {
        return () => {};
      }
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => list.removeEventListener("change", notify);
    },
    [query],
  );
  const snapshot = () => hasMatchMedia() && window.matchMedia(query).matches;
  return useSyncExternalStore(subscribe, snapshot, () => false);
}
