import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError, getOverview } from "../api.ts";
import { parseId } from "../route-params.ts";
import type { Overview } from "../types.ts";
import Button from "../ui/Button.tsx";
import EmptyState from "../ui/EmptyState.tsx";
import ErrorState from "../ui/ErrorState.tsx";
import Icon from "../ui/Icon.tsx";
import Skeleton from "../ui/Skeleton.tsx";
import { toApiError } from "../utils.ts";
import CreateProjectDialog from "./CreateProjectDialog.tsx";
import AttentionList from "./home/AttentionList.tsx";
import AutomationPausedBanner from "./home/AutomationPausedBanner.tsx";
import ProjectsList from "./home/ProjectsList.tsx";
import UpNext from "./home/UpNext.tsx";
import "./home/home.css";

type LoadState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "error"; message: string }
  | { status: "loaded"; overview: Overview };

/**
 * "What needs my attention, and what happens next?" Everything shown comes
 * from GET /api/overview (global, or ?project=<id> → ?project_id=<id>); the
 * frontend applies no attention rule of its own.
 */
function HomePage() {
  const [searchParams] = useSearchParams();
  const projectParam = searchParams.get("project");
  const projectId = projectParam === null ? null : parseId(projectParam);
  const invalidFilter = projectParam !== null && projectId === null;
  const key = projectId === null ? "all" : String(projectId);
  // The loaded state remembers which overview it is; another key reads as loading.
  const [loaded, setLoaded] = useState<{
    key: string;
    state: LoadState;
  } | null>(null);
  const [version, setVersion] = useState(0);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (invalidFilter) {
      return;
    }
    let active = true;
    const settle = (state: LoadState) => active && setLoaded({ key, state });
    getOverview(projectId ?? undefined)
      .then((overview) => settle({ status: "loaded", overview }))
      .catch((caught: unknown) =>
        settle(
          caught instanceof ApiError && caught.status === 404
            ? { status: "missing" }
            : { status: "error", message: toApiError(caught).message },
        ),
      );
    return () => {
      active = false;
    };
  }, [key, projectId, invalidFilter, version]);

  const state: LoadState = invalidFilter
    ? { status: "missing" }
    : loaded && loaded.key === key
      ? loaded.state
      : { status: "loading" };

  function retry() {
    setLoaded(null);
    setVersion((value) => value + 1);
  }

  const filtered = projectParam !== null;
  const overview = state.status === "loaded" ? state.overview : null;
  const filterName = filtered ? overview?.projects[0]?.name : undefined;

  return (
    <div className="ap-home">
      <h1 className="ap-page-title">Home</h1>
      {filterName && (
        <p className="ap-home-filter">
          <span>
            Showing <strong>{filterName}</strong>
          </span>
          <Link className="ap-link" to="/">
            Show all projects
          </Link>
        </p>
      )}

      {state.status === "loading" && (
        <div className="ap-home-sections">
          <Skeleton lines={3} label="Loading overview…" />
          <div aria-hidden="true" className="ap-home-sections">
            <Skeleton lines={2} />
            <Skeleton lines={2} />
          </div>
        </div>
      )}

      {state.status === "error" && (
        <ErrorState
          title="Couldn't load the overview"
          message={state.message}
          onRetry={retry}
        />
      )}

      {state.status === "missing" && (
        <EmptyState
          title="This project doesn't exist"
          description="It may have been removed, or the link is wrong."
          action={
            <Button as="link" to="/" variant="primary">
              Show all projects
            </Button>
          }
        />
      )}

      {overview && overview.projects.length === 0 && (
        <EmptyState
          title="Create your first project"
          description="A project groups the accounts, media and posts of one brand or channel."
          action={
            <Button
              variant="primary"
              icon="plus"
              onClick={() => setCreating(true)}
            >
              Create project
            </Button>
          }
        />
      )}

      {overview && overview.projects.length > 0 && (
        <div className="ap-home-sections">
          {overview.automation.paused && (
            <AutomationPausedBanner
              affected={overview.automation.paused_automatic_posts}
            />
          )}
          {overview.attention.length > 0 ? (
            <AttentionList items={overview.attention} />
          ) : (
            <section className="ap-home-ok" aria-labelledby="home-ok-title">
              <Icon name="check" className="ap-home-ok__icon" />
              <div>
                <h2 id="home-ok-title" className="ap-home-ok__title">
                  Everything looks good
                </h2>
                <p className="ap-home-ok__text">
                  Nothing needs your attention right now.
                </p>
              </div>
            </section>
          )}
          <UpNext posts={overview.upcoming} />
          <ProjectsList
            projects={overview.projects}
            onNewProject={filtered ? undefined : () => setCreating(true)}
          />
        </div>
      )}

      <CreateProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

export default HomePage;
