import { useEffect, useState } from "react";
import { useParams } from "react-router";
import { ApiError, getContent } from "../../api.ts";
import { parseId } from "../../route-params.ts";
import NotFound from "../../shell/NotFound.tsx";
import type { Content } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import PublishTask from "./PublishTask.tsx";

type MediaState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error"; message: string }
  | { status: "loaded"; media: Content };

/**
 * /p/:projectId/library/:mediaId/publish[?posts=…]: the Publish task of one
 * Media (a task route: no bottom navigation on phones). A Media of another
 * project, or one that doesn't exist, is "not found".
 */
function PublishMediaPage() {
  const { project } = useProject();
  const { mediaId } = useParams();
  const id = mediaId === undefined ? null : parseId(mediaId);
  // The result of the last read, for this id and attempt; anything else is
  // still loading (derived, so changing the Media never shows a stale one).
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    state: MediaState;
  } | null>(null);
  const key = `${id}:${project.id}:${attempt}`;

  useEffect(() => {
    if (id === null) {
      return;
    }
    let active = true;
    const done = (state: MediaState) => active && setResult({ key, state });
    getContent(id)
      .then((media) =>
        done(
          media.project_id === project.id
            ? { status: "loaded", media }
            : { status: "missing" },
        ),
      )
      .catch((caught: unknown) =>
        done(
          caught instanceof ApiError && caught.status === 404
            ? { status: "missing" }
            : { status: "error", message: toApiError(caught).message },
        ),
      );
    return () => {
      active = false;
    };
  }, [id, project.id, key]);
  const state: MediaState =
    result?.key === key ? result.state : { status: "loading" };

  const base = `/p/${project.id}`;
  if (id === null || state.status === "missing") {
    return (
      <NotFound backTo={{ to: `${base}/library`, label: "Back to Library" }} />
    );
  }
  if (state.status === "error") {
    return (
      <ErrorState
        title="Couldn't open Publish"
        message={state.message}
        onRetry={() => setAttempt((value) => value + 1)}
      />
    );
  }
  if (state.status === "loading") {
    return (
      <div className="ap-publish" aria-busy="true">
        <Skeleton lines={5} label="Loading Publish…" />
      </div>
    );
  }
  // Keyed by Media: another Media is another task.
  return (
    <PublishTask key={state.media.id} project={project} media={state.media} />
  );
}

export default PublishMediaPage;
