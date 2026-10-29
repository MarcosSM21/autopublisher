import { useCallback, useEffect, useState } from "react";
import {
  getAnalyticsAccounts,
  getAnalyticsPosts,
  refreshProjectAnalytics,
} from "../../api.ts";
import type { AccountCapability, PostAnalyticsRow } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import EmptyState from "../../ui/EmptyState.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import CapabilityPanel from "./CapabilityPanel.tsx";
import PostsTable from "./PostsTable.tsx";
import "./analytics.css";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "loaded";
      accounts: AccountCapability[];
      rows: PostAnalyticsRow[];
    };

function refreshSummary(result: {
  queued: number;
  in_cooldown: number;
  not_eligible: number;
}): string {
  const parts = [
    `${result.queued} queued`,
    result.in_cooldown > 0 ? `${result.in_cooldown} updated recently` : null,
    result.not_eligible > 0
      ? `${result.not_eligible} can't be refreshed`
      : null,
  ].filter(Boolean);
  return `Update requested: ${parts.join(", ")}.`;
}

/**
 * /p/:projectId/analytics: what each account can show and every published post
 * with its latest valid metrics. Refreshing only queues the work (the backend
 * reads in the background); the page loads again on request, never polls.
 */
function AnalyticsPage() {
  const { project } = useProject();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    () =>
      Promise.all([
        getAnalyticsAccounts(project.id),
        getAnalyticsPosts(project.id),
      ])
        .then(([accounts, rows]) =>
          setState({ status: "loaded", accounts, rows }),
        )
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [project.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshProject() {
    setRefreshing(true);
    setNotice(null);
    try {
      setNotice(refreshSummary(await refreshProjectAnalytics(project.id)));
      await load();
    } catch (caught) {
      setNotice(toApiError(caught).message);
    } finally {
      setRefreshing(false);
    }
  }

  const loaded = state.status === "loaded" ? state : null;
  return (
    <div className="ap-analytics">
      <div className="ap-page-header">
        <h1 className="ap-page-title">Analytics</h1>
        {loaded && loaded.rows.length > 0 && (
          <div className="ap-analytics__page-actions">
            <Button variant="ghost" onClick={() => void load()}>
              Reload
            </Button>
            <Button
              variant="primary"
              loading={refreshing}
              onClick={() => void refreshProject()}
            >
              Refresh project
            </Button>
          </div>
        )}
      </div>
      <p className="ap-analytics__notice" role="status">
        {notice}
      </p>

      {state.status === "loading" && (
        <Skeleton lines={4} label="Loading analytics…" />
      )}
      {state.status === "error" && (
        <ErrorState
          title="Couldn't load the analytics"
          message={state.message}
          onRetry={() => void load()}
        />
      )}
      {loaded && loaded.accounts.length > 0 && (
        <CapabilityPanel accounts={loaded.accounts} />
      )}
      {loaded && loaded.rows.length === 0 && (
        <EmptyState
          title="No published posts yet"
          description="Metrics appear here for the posts AutoPublisher publishes."
          action={
            <Button as="link" to={`/p/${project.id}/posts`} variant="primary">
              Go to Posts
            </Button>
          }
        />
      )}
      {loaded && loaded.rows.length > 0 && (
        <section aria-labelledby="analytics-posts">
          <h2 id="analytics-posts" className="ap-section-title">
            Published posts
          </h2>
          <p className="ap-meta">
            Each platform counts in its own way: metrics are never added up or
            compared across platforms.
          </p>
          <PostsTable
            rows={loaded.rows}
            accountsPath={`/p/${project.id}/accounts`}
            onQueued={() => void load()}
          />
        </section>
      )}
    </div>
  );
}

export default AnalyticsPage;
