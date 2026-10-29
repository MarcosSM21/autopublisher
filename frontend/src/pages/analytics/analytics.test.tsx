import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type {
  AccountCapability,
  MetricValue,
  PostAnalyticsRow,
  Project,
  RefreshState,
} from "../../types.ts";

let api: FakeApi;
let project: Project;
let nextId = 1;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  nextId = 1;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const YESTERDAY = new Date(Date.now() - 86_400_000).toISOString();

function metric(
  name: string,
  value: number | null,
  concept: string | null,
): MetricValue {
  return {
    name,
    label: name,
    value,
    available: value !== null,
    origin: "public_counter",
    concept,
    definition: `${name} as the platform reports it.`,
  };
}

function refresh(overrides: Partial<RefreshState> = {}): RefreshState {
  return {
    status: "ok",
    last_success_at: YESTERDAY,
    last_attempt_at: YESTERDAY,
    next_attempt_at: null,
    manual_pending: false,
    error_code: null,
    error_message: null,
    cooldown_until: null,
    ...overrides,
  };
}

function youtube(overrides: Partial<PostAnalyticsRow> = {}): PostAnalyticsRow {
  return {
    publication_id: nextId++,
    content_id: 1,
    content_type: "video",
    title: "Summer teaser",
    platform: "youtube",
    account_id: 1,
    account_label: "YouTube @cyber",
    published_at: YESTERDAY,
    age_days: 3,
    remote_url: "https://www.youtube.com/watch?v=VIDEO1",
    link_state: "linked",
    not_linked_reason: null,
    capability_state: "supported",
    metrics: [
      metric("viewCount", 200, "views"),
      metric("likeCount", 0, "likes"),
      metric("commentCount", 10, "comments"),
    ],
    engagement: {
      available: true,
      value: 0.05,
      formula: "(likeCount + commentCount) / viewCount",
      components: { likeCount: 0, commentCount: 10, viewCount: 200 },
    },
    refresh: refresh(),
    captured_at: YESTERDAY,
    ranked: null,
    ...overrides,
  };
}

function instagram(
  overrides: Partial<PostAnalyticsRow> = {},
): PostAnalyticsRow {
  return youtube({
    content_type: "image",
    title: "Beach photo",
    platform: "instagram",
    account_id: 2,
    account_label: "Instagram @cyber.ig",
    remote_url: "https://www.instagram.com/p/IG1/",
    metrics: [
      metric("like_count", null, "likes"),
      metric("comments_count", 4, "comments"),
    ],
    engagement: null,
    ...overrides,
  });
}

function account(
  label: string,
  capability: AccountCapability["capability"],
): AccountCapability {
  return {
    account_id: nextId++,
    platform: "youtube",
    label,
    capability,
  };
}

async function openPage(rows: PostAnalyticsRow[]) {
  api.analyticsPosts.set(project.id, rows);
  renderRoute(`/p/${project.id}/analytics`, { api });
  return screen.findByRole("heading", { level: 1, name: "Analytics" });
}

async function card(title: string): Promise<HTMLElement> {
  return screen.findByRole("listitem", { name: title });
}

describe("Analytics page", () => {
  it("shows original metrics, a real 0 and the visible engagement formula", async () => {
    await openPage([youtube()]);
    const post = await card("Summer teaser");

    const views = within(post).getByText("viewCount").closest("div")!;
    expect(views).toHaveTextContent("Views");
    expect(views).toHaveTextContent("200");
    // A real 0 is a value, never "Not available".
    const likes = within(post).getByText("likeCount").closest("div")!;
    expect(likes).toHaveTextContent("0");
    expect(likes).not.toHaveTextContent("Not available");
    expect(
      within(post).getByText("Engagement (calculated by AutoPublisher)"),
    ).toBeInTheDocument();
    expect(within(post).getByText("5%")).toBeInTheDocument();
    expect(
      within(post).getByText("(likeCount + commentCount) / viewCount"),
    ).toBeInTheDocument();
    expect(within(post).getByText("Up to date")).toBeInTheDocument();
    expect(within(post).getByText(/Published 3 days ago/)).toBeInTheDocument();
    const link = within(post).getByRole("link", { name: /Open on YouTube/ });
    expect(link).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=VIDEO1",
    );
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("shows a hidden Instagram like count as not available, without engagement", async () => {
    await openPage([instagram()]);
    const post = await card("Beach photo");

    const likes = within(post).getByText("like_count").closest("div")!;
    expect(likes).toHaveTextContent("Not available");
    expect(likes).not.toHaveTextContent(/\b0\b/);
    expect(
      within(post).getByText("comments_count").closest("div")!,
    ).toHaveTextContent("4");
    expect(within(post).queryByText(/Engagement/)).not.toBeInTheDocument();
  });

  it("an unavailable engagement is never 0", async () => {
    await openPage([
      youtube({
        metrics: [metric("viewCount", 0, "views")],
        engagement: {
          available: false,
          value: null,
          formula: "(likeCount + commentCount) / viewCount",
          components: { likeCount: null, commentCount: null, viewCount: 0 },
        },
      }),
    ]);
    const post = await card("Summer teaser");

    const engagement = within(post)
      .getByText("Engagement (calculated by AutoPublisher)")
      .closest("div")!;
    expect(engagement).toHaveTextContent("Not available");
    expect(engagement).not.toHaveTextContent("0%");
  });

  it("keeps the last valid metrics next to a later failure", async () => {
    await openPage([
      youtube({
        refresh: refresh({ status: "stale", error_code: "refresh_failed" }),
      }),
    ]);
    const post = await card("Summer teaser");

    expect(within(post).getByText("Out of date")).toBeInTheDocument();
    expect(within(post).getByText(/Last valid update:/)).toBeInTheDocument();
    expect(
      within(post).getByText(
        "Couldn't update again: AutoPublisher will try again later.",
      ),
    ).toBeInTheDocument();
    expect(
      within(post).getByText("viewCount").closest("div")!,
    ).toHaveTextContent("200");
  });

  it.each([
    ["pending", "Updating"],
    ["rate_limited", "Paused by the platform"],
    ["permission_required", "Permission needed"],
    ["remote_not_found", "Not found yet"],
    ["remote_deleted", "Deleted on the platform"],
  ] as const)("shows the %s state", async (status, label) => {
    await openPage([youtube({ refresh: refresh({ status }) })]);
    const post = await card("Summer teaser");

    expect(within(post).getByText(label)).toBeInTheDocument();
  });

  it("links to Accounts when reconnection is needed", async () => {
    await openPage([
      youtube({
        capability_state: "reconnect_required",
        refresh: refresh({ status: "reconnect_required" }),
      }),
    ]);
    const post = await card("Summer teaser");

    expect(
      within(post).getByText(
        "Reconnect this account to read its metrics again.",
      ),
    ).toBeInTheDocument();
    expect(
      within(post).getByRole("link", { name: "Go to Accounts" }),
    ).toHaveAttribute("href", `/p/${project.id}/accounts`);
    // No refresh while the account can't be read.
    expect(
      within(post).queryByRole("button", { name: "Refresh" }),
    ).not.toBeInTheDocument();
  });

  it("a never read post waits for its first reading", async () => {
    await openPage([
      youtube({
        captured_at: null,
        metrics: [metric("viewCount", null, "views")],
        engagement: null,
        refresh: refresh({ status: "pending", last_success_at: null }),
      }),
    ]);
    const post = await card("Summer teaser");

    expect(
      within(post).getByText("Waiting for its first reading."),
    ).toBeInTheDocument();
    // No grid of blanks before the first reading.
    expect(within(post).queryByText("viewCount")).not.toBeInTheDocument();
    expect(within(post).queryByText("Not available")).not.toBeInTheDocument();
  });

  it.each([
    [
      { link_state: "not_linked", not_linked_reason: "remote_id_missing" },
      "AutoPublisher has no remote id for this post.",
    ],
    [
      {
        link_state: "not_linked",
        not_linked_reason: "remote_identity_changed",
      },
      /Published by another account than the one connected now/,
    ],
    [
      { capability_state: "not_supported", platform: "telegram" },
      "AutoPublisher doesn't read this platform's metrics in this version.",
    ],
    [
      { capability_state: "permission_required", platform: "threads" },
      "These metrics need a permission AutoPublisher doesn't request yet.",
    ],
  ] as const)(
    "explains why a post has no metrics (%o)",
    async (overrides, text) => {
      await openPage([
        youtube({
          ...(overrides as Partial<PostAnalyticsRow>),
          metrics: [],
          engagement: null,
          refresh: null,
          captured_at: null,
          remote_url: null,
        }),
      ]);
      const post = await card("Summer teaser");

      expect(within(post).getByText(text)).toBeInTheDocument();
      expect(within(post).getByText("Never read.")).toBeInTheDocument();
      expect(
        within(post).queryByRole("button", { name: "Refresh" }),
      ).not.toBeInTheDocument();
    },
  );

  it("shows what each account can read, including partial Instagram", async () => {
    api.analyticsAccounts.set(project.id, [
      account("YouTube @cyber", {
        state: "supported",
        groups: [
          { group: "basic", state: "supported", missing_permission: null },
        ],
        reason: null,
      }),
      account("Instagram @cyber.ig", {
        state: "supported",
        groups: [
          { group: "basic", state: "supported", missing_permission: null },
          {
            group: "insights",
            state: "permission_required",
            missing_permission: "instagram_business_manage_insights",
          },
        ],
        reason: null,
      }),
      account("Telegram @cyber", {
        state: "not_supported",
        groups: [],
        reason: null,
      }),
      account("X @cyber", {
        state: "not_applicable",
        groups: [],
        reason: null,
      }),
      account("Threads @cyber", {
        state: "not_connected",
        groups: [
          {
            group: "insights",
            state: "not_connected",
            missing_permission: null,
          },
        ],
        reason: null,
      }),
    ]);
    await openPage([youtube()]);
    const panel = await screen.findByRole("region", {
      name: "What each account can show",
    });

    const ig = within(panel).getByText("Instagram @cyber.ig").closest("li")!;
    expect(ig).toHaveTextContent("Metrics available");
    expect(ig).toHaveTextContent("Public counters: metrics available");
    expect(ig).toHaveTextContent(
      "Insights: permission needed (instagram_business_manage_insights)",
    );
    expect(
      within(panel).getByText("Telegram @cyber").closest("li")!,
    ).toHaveTextContent("Not supported yet");
    expect(
      within(panel).getByText("X @cyber").closest("li")!,
    ).toHaveTextContent("Not applicable");
    expect(
      within(panel).getByText("Threads @cyber").closest("li")!,
    ).toHaveTextContent("Not connected");
  });

  it("refreshes one post and shows it queued", async () => {
    const row = youtube();
    await openPage([row]);
    const post = await card("Summer teaser");

    await userEvent.click(
      within(post).getByRole("button", { name: "Refresh" }),
    );

    expect(
      await within(await card("Summer teaser")).findByText("Updating"),
    ).toBeInTheDocument();
    expect(
      api.requests.some(
        (r) =>
          r.method === "POST" &&
          r.path === `/publications/${row.publication_id}/analytics/refresh`,
      ),
    ).toBe(true);
  });

  it("explains the cooldown and when it ends", async () => {
    const row = youtube();
    const availableAt = new Date(Date.now() + 10 * 60_000).toISOString();
    api.analyticsRefresh.set(row.publication_id, {
      code: "refresh_cooldown",
      available_at: availableAt,
    });
    await openPage([row]);
    const post = await card("Summer teaser");

    await userEvent.click(
      within(post).getByRole("button", { name: "Refresh" }),
    );

    expect(
      await within(post).findByText(
        /Updated recently\. You can refresh again Today/,
      ),
    ).toBeInTheDocument();
    expect(within(post).getByText("Up to date")).toBeInTheDocument();
  });

  it("explains why a post can't be refreshed", async () => {
    const row = youtube();
    api.analyticsRefresh.set(row.publication_id, {
      code: "analytics_not_refreshable",
      reason: "remote_identity_changed",
      message: "This post was published by another account.",
    });
    await openPage([row]);
    const post = await card("Summer teaser");

    await userEvent.click(
      within(post).getByRole("button", { name: "Refresh" }),
    );

    expect(
      await within(post).findByText(
        "This post was published by another account.",
      ),
    ).toBeInTheDocument();
  });

  it("refreshes the whole project and reports the counts", async () => {
    api.analyticsProjectRefresh = {
      queued: 2,
      in_cooldown: 1,
      not_eligible: 3,
    };
    await openPage([youtube(), instagram()]);

    await userEvent.click(
      await screen.findByRole("button", { name: "Refresh project" }),
    );

    expect(
      await screen.findByText(
        "Update requested: 2 queued, 1 updated recently, 3 can't be refreshed.",
      ),
    ).toBeInTheDocument();
  });

  it("never shows totals across platforms", async () => {
    await openPage([youtube(), instagram()]);
    await card("Beach photo");

    expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
    expect(screen.getByText(/never added up or compared/)).toBeInTheDocument();
  });

  it("an empty project points to Posts", async () => {
    await openPage([]);

    expect(
      await screen.findByRole("heading", { name: "No published posts yet" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Posts" })).toHaveAttribute(
      "href",
      `/p/${project.id}/posts`,
    );
  });

  it("shows an API error with a retry", async () => {
    api.failRequest("GET", `/projects/${project.id}/analytics/posts`, 503, {
      error: { code: "unavailable", message: "Try again.", fields: [] },
    });
    await openPage([youtube()]);

    expect(
      await screen.findByText("Couldn't load the analytics"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await card("Summer teaser")).toBeInTheDocument();
  });

  it("works at phone width", async () => {
    vi.stubGlobal(
      "matchMedia",
      (query: string) =>
        ({
          matches: 375 >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
          media: query,
          addEventListener: () => {},
          removeEventListener: () => {},
        }) as unknown as MediaQueryList,
    );
    await openPage([youtube()]);
    const post = await card("Summer teaser");

    expect(within(post).getByRole("button", { name: "Refresh" })).toBeVisible();
    // The bottom bar has the Analytics destination too.
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(
      within(nav).getByRole("link", { name: "Analytics" }),
    ).toHaveAttribute("aria-current", "page");
  });
});
