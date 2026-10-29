import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { getContentAnalytics } from "../../api.ts";
import type { ContentSideBySide } from "../../types.ts";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import SideBySide from "./SideBySide.tsx";
import "./analytics.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; view: ContentSideBySide };

/** /p/:projectId/analytics/media/:contentId: one media's posts side by side. */
function ContentAnalyticsPage() {
  const { project } = useProject();
  const contentId = Number(useParams().contentId);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(
    () =>
      getContentAnalytics(contentId)
        .then((view) => setState({ status: "loaded", view }))
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [contentId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="ap-analytics">
      <Link className="ap-link" to={`/p/${project.id}/analytics`}>
        Back to Analytics
      </Link>
      <div className="ap-page-header">
        <h1 className="ap-page-title">Media side by side</h1>
      </div>
      {state.status === "loading" && (
        <Skeleton lines={4} label="Loading the media's metrics…" />
      )}
      {state.status === "error" && (
        <ErrorState
          title="Couldn't load this media's metrics"
          message={state.message}
          onRetry={() => void load()}
        />
      )}
      {state.status === "loaded" && (
        <SideBySide
          view={state.view}
          accountsPath={`/p/${project.id}/accounts`}
        />
      )}
    </div>
  );
}

export default ContentAnalyticsPage;
