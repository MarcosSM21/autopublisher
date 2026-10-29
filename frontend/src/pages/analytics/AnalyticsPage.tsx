import { useCallback, useEffect, useRef, useState } from "react";
import {
  getAnalyticsAccounts,
  getAnalyticsCatalog,
  getAnalyticsPosts,
  getContentTypeSummary,
  refreshProjectAnalytics,
} from "../../api.ts";
import type {
  AccountCapability,
  AnalyticsCatalog,
  ContentTypeSummary,
  PostAnalyticsRow,
} from "../../types.ts";
import { platformLabel } from "../../types.ts";
import Button from "../../ui/Button.tsx";
import EmptyState from "../../ui/EmptyState.tsx";
import ErrorState from "../../ui/ErrorState.tsx";
import Field from "../../ui/Field.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { toApiError } from "../../utils.ts";
import { useProject } from "../project-context.ts";
import CapabilityPanel from "./CapabilityPanel.tsx";
import ContentTypeSummaryList from "./ContentTypeSummary.tsx";
import { CONCEPT_LABELS } from "./copy.ts";
import PostsTable from "./PostsTable.tsx";
import "./analytics.css";

const ENGAGEMENT = "engagement";

interface Filters {
  /** One account (and so one platform): rankings and summaries need it. */
  accountId: number | null;
  from: string;
  to: string;
  /** A metric name of the account's platform, or `engagement`. */
  sort: string;
}

const NO_FILTERS: Filters = { accountId: null, from: "", to: "", sort: "" };

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "loaded";
      accounts: AccountCapability[];
      catalog: AnalyticsCatalog;
      rows: PostAnalyticsRow[];
      /** Only with an account selected. */
      summaries: ContentTypeSummary[] | null;
    };

interface SortOption {
  value: string;
  label: string;
}

/** The metrics this account's platform reads now (supported groups only). */
function sortOptions(
  account: AccountCapability | undefined,
  catalog: AnalyticsCatalog,
): SortOption[] {
  if (!account) return [];
  const platform = catalog.platforms.find(
    (item) => item.platform === account.platform,
  );
  if (!platform) return [];
  const readable = new Set(
    account.capability.groups
      .filter((group) => group.state === "supported")
      .map((group) => group.group),
  );
  const options = platform.metrics
    .filter((metric) => readable.has(metric.group))
    .map((metric) => ({
      value: metric.name,
      label: `${(metric.concept && CONCEPT_LABELS[metric.concept]) ?? metric.label} (${metric.name})`,
    }));
  if (options.length > 0 && platform.engagement) {
    options.push({ value: ENGAGEMENT, label: "Engagement (calculated)" });
  }
  return options;
}

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
 * with its latest valid metrics. Choosing one account ranks its posts by one of
 * its platform's metrics and summarizes them by content type; nothing is ranked
 * or summarized across platforms. Refreshing only queues the work (the backend
 * reads in the background); the page loads again on request, never polls.
 */
function AnalyticsPage() {
  const { project } = useProject();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Only the latest load may land: a slower answer for older filters is dropped.
  const latestLoad = useRef(0);

  const load = useCallback(() => {
    const loadId = ++latestLoad.current;
    const period = {
      published_from: filters.from || undefined,
      published_to: filters.to || undefined,
    };
    return Promise.all([
      getAnalyticsAccounts(project.id),
      getAnalyticsCatalog(),
    ])
      .then(([accounts, catalog]) => {
        const account = accounts.find(
          (a) => a.account_id === filters.accountId,
        );
        const scope = account
          ? { platform: account.platform, account_id: account.account_id }
          : {};
        return Promise.all([
          getAnalyticsPosts(project.id, {
            ...scope,
            ...period,
            sort: account && filters.sort ? filters.sort : undefined,
          }),
          account
            ? getContentTypeSummary(project.id, {
                platform: account.platform,
                account_id: account.account_id,
                ...period,
              })
            : null,
        ]).then(([rows, summaries]) => {
          if (loadId === latestLoad.current) {
            setState({ status: "loaded", accounts, catalog, rows, summaries });
          }
        });
      })
      .catch((caught: unknown) => {
        if (loadId === latestLoad.current) {
          setState({ status: "error", message: toApiError(caught).message });
        }
      });
  }, [project.id, filters]);

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
  const filtered =
    filters.accountId !== null || filters.from !== "" || filters.to !== "";
  const showPosts = loaded && (loaded.rows.length > 0 || filtered);
  const account = loaded?.accounts.find(
    (a) => a.account_id === filters.accountId,
  );
  const options = loaded ? sortOptions(account, loaded.catalog) : [];
  const sortLabel = options.find((o) => o.value === filters.sort)?.label;
  const ranking = account && sortLabel ? sortLabel : null;

  return (
    <div className="ap-analytics">
      <div className="ap-page-header">
        <h1 className="ap-page-title">Analytics</h1>
        {showPosts && (
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
      {loaded && !showPosts && (
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
      {loaded && showPosts && (
        <>
          <section className="ap-analytics__filters" aria-label="Choose posts">
            <Field label="Account">
              {(control) => (
                <select
                  {...control}
                  value={filters.accountId ?? ""}
                  onChange={(event) =>
                    setFilters({
                      ...filters,
                      accountId: event.target.value
                        ? Number(event.target.value)
                        : null,
                      // Each platform has its own metrics.
                      sort: "",
                    })
                  }
                >
                  <option value="">All accounts (newest first)</option>
                  {loaded.accounts.map((item) => (
                    <option key={item.account_id} value={item.account_id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field
              label="Rank by"
              hint={
                !account
                  ? "Choose one account to rank its posts by one of its metrics."
                  : options.length === 0
                    ? "AutoPublisher reads no metrics of this account to rank by."
                    : `Only ${platformLabel(account.platform)} metrics, within this account.`
              }
            >
              {(control) => (
                <select
                  {...control}
                  value={filters.sort}
                  disabled={options.length === 0}
                  onChange={(event) =>
                    setFilters({ ...filters, sort: event.target.value })
                  }
                >
                  <option value="">Newest first (no ranking)</option>
                  {options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Published from">
              {(control) => (
                <input
                  {...control}
                  type="date"
                  value={filters.from}
                  max={filters.to || undefined}
                  onChange={(event) =>
                    setFilters({ ...filters, from: event.target.value })
                  }
                />
              )}
            </Field>
            <Field label="Published to">
              {(control) => (
                <input
                  {...control}
                  type="date"
                  value={filters.to}
                  min={filters.from || undefined}
                  onChange={(event) =>
                    setFilters({ ...filters, to: event.target.value })
                  }
                />
              )}
            </Field>
          </section>

          {account && loaded.summaries && (
            <section aria-labelledby="analytics-types">
              <h2 id="analytics-types" className="ap-section-title">
                By content type · {account.label}
              </h2>
              <p className="ap-meta">
                Medians of this account&apos;s posts, over the posts that have
                each metric. Not compared with other platforms.
              </p>
              <ContentTypeSummaryList summaries={loaded.summaries} />
            </section>
          )}

          {ranking && account ? (
            <RankingSection
              rows={loaded.rows}
              account={account}
              metric={ranking}
              accountsPath={`/p/${project.id}/accounts`}
              onQueued={() => void load()}
            />
          ) : (
            <section aria-labelledby="analytics-posts">
              <h2 id="analytics-posts" className="ap-section-title">
                Published posts
              </h2>
              <p className="ap-meta">
                Each platform counts in its own way: metrics are never added up
                or compared across platforms.
              </p>
              {loaded.rows.length === 0 ? (
                <p className="ap-meta">No posts published in this period.</p>
              ) : (
                <PostsTable
                  rows={loaded.rows}
                  accountsPath={`/p/${project.id}/accounts`}
                  onQueued={() => void load()}
                />
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

interface RankingSectionProps {
  rows: PostAnalyticsRow[];
  account: AccountCapability;
  metric: string;
  accountsPath: string;
  onQueued: () => void;
}

/** One account's posts by one metric; posts without it are listed apart. */
function RankingSection({
  rows,
  account,
  metric,
  accountsPath,
  onQueued,
}: RankingSectionProps) {
  const ranked = rows.filter((row) => row.ranked);
  const unranked = rows.filter((row) => !row.ranked);
  return (
    <section aria-labelledby="analytics-ranking">
      <h2 id="analytics-ranking" className="ap-section-title">
        Top posts · {account.label}
      </h2>
      <p className="ap-meta">
        Ranked by {metric}, highest first, using each post&apos;s latest valid
        reading. Only {account.label} posts take part: this ranking is not
        compared with other platforms.
      </p>
      {rows.length === 0 && (
        <p className="ap-meta">No posts published in this period.</p>
      )}
      {ranked.length > 0 && (
        <PostsTable
          rows={ranked}
          ranked
          label={`Ranking by ${metric}`}
          accountsPath={accountsPath}
          onQueued={onQueued}
        />
      )}
      {unranked.length > 0 && (
        <>
          <h3 className="ap-analytics__subtitle">Not ranked</h3>
          <p className="ap-meta">
            These posts have no {metric} reading, so they aren&apos;t ranked (a
            missing metric never counts as 0).
          </p>
          <PostsTable
            rows={unranked}
            label="Not ranked"
            accountsPath={accountsPath}
            onQueued={onQueued}
          />
        </>
      )}
    </section>
  );
}

export default AnalyticsPage;
