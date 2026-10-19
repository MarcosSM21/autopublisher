import { useCallback, useEffect, useRef, useState } from "react";
import { listPublications } from "../../api.ts";
import type { Publication } from "../../types.ts";
import {
  AUTOMATION_POLL_INTERVAL_MS,
  awaitsAutomaticStart,
  POLL_INTERVAL_MS,
  toApiError,
} from "../../utils.ts";

/**
 * How often the list is read again: fast while a Post is publishing, slower
 * while armed Posts wait for the scheduler, never otherwise.
 */
export function pollInterval(posts: readonly Publication[]): number | null {
  if (posts.some((post) => post.display_state === "publishing")) {
    return POLL_INTERVAL_MS;
  }
  if (posts.some(awaitsAutomaticStart)) {
    return AUTOMATION_POLL_INTERVAL_MS;
  }
  return null;
}

/** Whether any Post appeared, disappeared or changed its visible state. */
export function statesChanged(
  before: readonly Publication[],
  after: readonly Publication[],
): boolean {
  if (before.length !== after.length) {
    return true;
  }
  const states = new Map(before.map((post) => [post.id, post.display_state]));
  return after.some((post) => states.get(post.id) !== post.display_state);
}

export type PostsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; posts: Publication[] };

/**
 * The project's Posts for the Posts page, its detail and Calendar: one list
 * request, one poller. When a visible state changes, `onStatusChange` lets the
 * project's overview (readiness) be read again.
 */
export function usePostsData(projectId: number, onStatusChange: () => void) {
  const [state, setState] = useState<PostsState>({ status: "loading" });
  const previous = useRef<Publication[] | null>(null);
  const onChange = useRef(onStatusChange);
  useEffect(() => {
    onChange.current = onStatusChange;
  });

  const reload = useCallback(
    () =>
      listPublications(projectId)
        .then((posts) => {
          const before = previous.current;
          previous.current = posts;
          setState({ status: "loaded", posts });
          if (before !== null && statesChanged(before, posts)) {
            onChange.current();
          }
        })
        .catch((caught: unknown) => {
          // A failed refresh keeps the list already shown.
          if (previous.current === null) {
            setState({ status: "error", message: toApiError(caught).message });
          }
        }),
    [projectId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const posts = state.status === "loaded" ? state.posts : null;
  const interval = posts ? pollInterval(posts) : null;
  useEffect(() => {
    if (interval === null) {
      return;
    }
    const timer = window.setInterval(() => void reload(), interval);
    return () => window.clearInterval(timer);
  }, [interval, reload]);

  const byId = useCallback(
    (id: number) => posts?.find((post) => post.id === id) ?? null,
    [posts],
  );

  return { state, posts, reload, byId };
}
