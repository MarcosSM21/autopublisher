import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";
import { getAccountHealth, getPublication } from "../api.ts";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import type { AccountHealth, Publication } from "../types.ts";
import { MEDIA_MD_UP } from "../ui/breakpoints.ts";
import Button from "../ui/Button.tsx";
import ChoiceGroup from "../ui/ChoiceGroup.tsx";
import EmptyState from "../ui/EmptyState.tsx";
import ErrorState from "../ui/ErrorState.tsx";
import Field from "../ui/Field.tsx";
import Skeleton from "../ui/Skeleton.tsx";
import { useMediaQuery } from "../ui/useMediaQuery.ts";
import { accountName } from "../utils.ts";
import AutomationPausedBanner from "./home/AutomationPausedBanner.tsx";
import CalendarView from "./posts/CalendarView.tsx";
import DailyList from "./posts/DailyList.tsx";
import HistoryList from "./posts/HistoryList.tsx";
import NewPostMenu from "./posts/NewPostMenu.tsx";
import PostDetail from "./posts/PostDetail.tsx";
import { readinessOf, readinessSource } from "./posts/readiness.ts";
import {
  dailySections,
  filterPosts,
  HISTORY_PAGE_SIZE,
  historyGroups,
} from "./posts/sections.ts";
import { usePostsData } from "./posts/usePostsData.ts";
import "./home/home.css";
import "./posts/posts.css";
import { useProject } from "./project-context.ts";
import { useMissingFromProject } from "./useMissingFromProject.ts";

type View = "list" | "history" | "calendar";

function viewOf(param: string | null): View {
  return param === "history" || param === "calendar" ? param : "list";
}

/**
 * /p/:projectId/posts[/:postId][?view=history|calendar&q=&account=]: the
 * project's Posts by meaning (Needs you, Upcoming, Drafts), History apart and
 * Calendar, with the Post detail chosen by the URL. One list, one poller: the
 * list stays mounted behind the detail.
 */
function PostsPage() {
  const { project, overview, reloadOverview } = useProject();
  const { postId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = viewOf(params.get("view"));
  const query = params.get("q") ?? "";
  const accountId = parseId(params.get("account") ?? undefined);
  const selectedId = postId === undefined ? null : parseId(postId);
  const missing = useMissingFromProject(selectedId, project.id, getPublication);
  const data = usePostsData(project.id, reloadOverview);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [health, setHealth] = useState<AccountHealth[]>([]);
  const [historyShown, setHistoryShown] = useState(HISTORY_PAGE_SIZE);
  const base = `/p/${project.id}`;

  useEffect(() => {
    let active = true;
    getAccountHealth(project.id)
      .then((loaded) => active && setHealth(loaded))
      .catch(() => {
        // Without account health, Blocked readiness is just not shown.
      });
    return () => {
      active = false;
    };
  }, [project.id]);

  const source = useMemo(
    () => readinessSource(overview, health),
    [overview, health],
  );
  const posts = data.posts;
  const filtered = useMemo(
    () => (posts ? filterPosts(posts, query, accountId) : []),
    [posts, query, accountId],
  );
  const accounts = useMemo(() => {
    const seen = new Map<number, Publication["account"]>();
    for (const post of posts ?? []) {
      seen.set(post.account_id, post.account);
    }
    return [...seen.entries()];
  }, [posts]);

  // The search and the destination live in the URL (replace: no history).
  const setParam = (key: string, value: string | null) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) {
          next.set(key, value);
        } else {
          next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  const search = location.search;
  const rowPath = useCallback(
    (post: Publication) => `${base}/posts/${post.id}${search}`,
    [base, search],
  );
  const viewPath = (next: View) => {
    const nextParams = new URLSearchParams(params);
    nextParams.delete("week");
    if (next === "list") {
      nextParams.delete("view");
    } else {
      nextParams.set("view", next);
    }
    const query = nextParams.toString();
    return `${base}/posts${query ? `?${query}` : ""}`;
  };

  // Finish later lands here with the focus on Drafts (router state only).
  const draftsHeading = useRef<HTMLHeadingElement>(null);
  const handledFocus = useRef<string | null>(null);
  const wantsDrafts =
    (location.state as { focus?: string } | null)?.focus === "drafts";
  useEffect(() => {
    if (
      wantsDrafts &&
      posts !== null &&
      handledFocus.current !== location.key
    ) {
      handledFocus.current = location.key;
      const heading = draftsHeading.current;
      heading?.focus();
      heading?.scrollIntoView?.({ block: "start" });
    }
  }, [wantsDrafts, posts, location.key]);

  // A deep link can be opened before the list arrives: read that Post once.
  const listed = selectedId === null ? null : data.byId(selectedId);
  const [fallback, setFallback] = useState<Publication | null>(null);
  useEffect(() => {
    if (selectedId === null || listed !== null) {
      return;
    }
    let active = true;
    getPublication(selectedId)
      .then(
        (loaded) =>
          active && loaded.project_id === project.id && setFallback(loaded),
      )
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [selectedId, listed, project.id]);
  const selected = listed ?? (fallback?.id === selectedId ? fallback : null);

  // Closing the detail gives focus back to the row it was opened from.
  const previous = useRef(selectedId);
  useEffect(() => {
    const closed = previous.current;
    previous.current = selectedId;
    if (closed !== null && selectedId === null) {
      document
        .querySelector<HTMLElement>(`[data-detail-id="${closed}"]`)
        ?.focus();
    }
  }, [selectedId]);

  if ((postId !== undefined && selectedId === null) || missing) {
    return (
      <NotFound backTo={{ to: `${base}/posts`, label: "Back to Posts" }} />
    );
  }

  const paused = overview?.automation.paused === true;
  const sections = dailySections(filtered, source);
  const history = historyGroups(filtered, historyShown);
  const nothingAtAll = posts !== null && posts.length === 0;

  return (
    <div
      className={
        selectedId !== null
          ? `ap-posts ap-posts--with-detail${view === "calendar" ? "" : " ap-posts--panel-lg"}`
          : "ap-posts"
      }
    >
      {/* Hidden, not unmounted, behind a phone's full-page detail. */}
      <div className="ap-posts__list" hidden={selected !== null && !isMedium}>
        <header className="ap-posts__header ap-page-header">
          <h1 className="ap-page-title">Posts</h1>
          <ChoiceGroup
            legend="View"
            hideLegend
            variant="switch"
            choices={[
              { value: "list", label: "List" },
              { value: "calendar", label: "Calendar" },
            ]}
            value={view === "calendar" ? "calendar" : "list"}
            onChange={(next) => void navigate(viewPath(next))}
          />
          <NewPostMenu projectId={project.id} />
        </header>
        {paused && (
          <AutomationPausedBanner
            affected={overview?.automation.paused_automatic_posts ?? 0}
          />
        )}
        {!nothingAtAll && (
          <div className="ap-posts__toolbar">
            <Field label="Search posts" className="ap-posts__search">
              {(control) => (
                <input
                  {...control}
                  type="search"
                  value={query}
                  onChange={(event) => setParam("q", event.target.value)}
                />
              )}
            </Field>
            <Field label="Destination" className="ap-posts__account">
              {(control) => (
                <select
                  {...control}
                  value={accountId ?? ""}
                  onChange={(event) =>
                    setParam("account", event.target.value || null)
                  }
                >
                  <option value="">All destinations</option>
                  {accounts.map(([id, account]) => (
                    <option key={id} value={id}>
                      {accountName(account)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            {view === "list" && (
              <Button as="link" to={viewPath("history")} variant="ghost">
                History
              </Button>
            )}
            {view === "history" && (
              <Button
                as="link"
                to={viewPath("list")}
                variant="ghost"
                icon="back"
              >
                Back to Posts
              </Button>
            )}
          </div>
        )}
        {data.state.status === "error" ? (
          <ErrorState
            title="Couldn't load the posts"
            message={data.state.message}
            onRetry={() => void data.reload()}
          />
        ) : posts === null ? (
          <div aria-busy="true">
            <Skeleton lines={6} label="Loading posts…" />
          </div>
        ) : nothingAtAll ? (
          <EmptyState
            title="No posts yet"
            description="Open the Library to publish your media."
            headingLevel={2}
            action={
              <Button as="link" variant="primary" to={`${base}/library`}>
                Open the Library
              </Button>
            }
          />
        ) : view === "calendar" ? (
          <CalendarView
            posts={filtered}
            rowPath={rowPath}
            selectedId={selectedId}
          />
        ) : view === "history" ? (
          <>
            <h2 className="ap-section-title">History</h2>
            <HistoryList
              groups={history.groups}
              total={history.total}
              shown={Math.min(historyShown, history.total)}
              onShowMore={() =>
                setHistoryShown((shown) => shown + HISTORY_PAGE_SIZE)
              }
              rowPath={rowPath}
              selectedId={selectedId}
            />
          </>
        ) : filtered.length === 0 ? (
          <p className="ap-meta">No posts match this search.</p>
        ) : (
          <DailyList
            sections={sections}
            readiness={source}
            rowPath={rowPath}
            selectedId={selectedId}
            draftsHeading={draftsHeading}
          />
        )}
      </div>
      {selected && (
        <PostDetail
          key={selected.id}
          post={selected}
          project={project}
          readiness={readinessOf(selected, source)}
          paused={paused}
          posts={posts ?? []}
          parentPath={`${base}/posts${search}`}
          panelFrom={view === "calendar" ? "never" : "lg"}
          onChanged={() => void data.reload()}
        />
      )}
    </div>
  );
}

export default PostsPage;
