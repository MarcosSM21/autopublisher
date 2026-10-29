import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type {
  AccountCapability,
  AnalyticsCatalog,
  ContentTypeSummary,
  MetricValue,
  PostAnalyticsRow,
  Project,
} from "../../types.ts";

let api: FakeApi;
let project: Project;
let nextId = 1;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  nextId = 1;
  api.analyticsCatalog = CATALOG;
  api.analyticsAccounts.set(project.id, [YOUTUBE, INSTAGRAM]);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const READ = "2026-10-20T10:00:00Z";

function definition(name: string, concept: string | null, group = "basic") {
  return {
    name,
    label: name,
    definition: `${name} as the platform reports it.`,
    origin: "public_counter" as const,
    concept,
    group,
  };
}

const CATALOG: AnalyticsCatalog = {
  concepts: [],
  platforms: [
    {
      platform: "youtube",
      metrics: [
        definition("viewCount", "views", "statistics"),
        definition("likeCount", "likes", "statistics"),
        definition("commentCount", "comments", "statistics"),
      ],
      excluded: [],
      engagement: {
        numerator: ["likeCount", "commentCount"],
        denominator: "viewCount",
      },
    },
    {
      platform: "instagram",
      metrics: [
        definition("like_count", "likes"),
        definition("comments_count", "comments"),
        definition("views", "views", "insights"),
      ],
      excluded: [],
      engagement: null,
    },
  ],
};

const YOUTUBE: AccountCapability = {
  account_id: 1,
  platform: "youtube",
  label: "YouTube @cyber",
  capability: {
    state: "supported",
    groups: [
      { group: "statistics", state: "supported", missing_permission: null },
    ],
    reason: null,
  },
};

const INSTAGRAM: AccountCapability = {
  account_id: 2,
  platform: "instagram",
  label: "Instagram @cyber.ig",
  capability: {
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
  },
};

function metric(name: string, value: number | null): MetricValue {
  return {
    name,
    label: name,
    value,
    available: value !== null,
    origin: "public_counter",
    concept: null,
    definition: name,
  };
}

function post(
  title: string,
  account: AccountCapability,
  publishedAt: string,
  metrics: MetricValue[],
): PostAnalyticsRow {
  return {
    publication_id: nextId++,
    content_id: null,
    content_type: "text",
    title,
    platform: account.platform,
    account_id: account.account_id,
    account_label: account.label,
    published_at: publishedAt,
    age_days: 4,
    remote_url: null,
    link_state: "linked",
    not_linked_reason: null,
    capability_state: "supported",
    metrics,
    engagement: null,
    refresh: null,
    captured_at: READ,
    ranked: null,
  };
}

function median(count: number, value: number | null) {
  return { count, insufficient_sample: count < 3, value };
}

const SUMMARY: ContentTypeSummary[] = [
  {
    content_type: "video",
    posts_total: 4,
    posts_with_data: 3,
    insufficient_sample: false,
    median_age_days: 5,
    medians: [
      {
        name: "viewCount",
        label: "viewCount",
        concept: "views",
        ...median(3, 120),
      },
      {
        name: "likeCount",
        label: "likeCount",
        concept: "likes",
        ...median(2, null),
      },
    ],
    engagement_median: median(3, 0.04),
  },
  {
    content_type: "image",
    posts_total: 2,
    posts_with_data: 2,
    insufficient_sample: true,
    median_age_days: 1,
    medians: [
      {
        name: "viewCount",
        label: "viewCount",
        concept: "views",
        ...median(2, null),
      },
    ],
    engagement_median: median(2, null),
  },
];

function seed() {
  api.analyticsPosts.set(project.id, [
    post("Few views", YOUTUBE, "2026-10-18T10:00:00Z", [
      metric("viewCount", 10),
      metric("likeCount", 0),
    ]),
    post("Not read for views", YOUTUBE, "2026-10-17T10:00:00Z", [
      metric("viewCount", null),
      metric("likeCount", 9),
    ]),
    post("Many views", YOUTUBE, "2026-09-01T10:00:00Z", [
      metric("viewCount", 900),
      metric("likeCount", 3),
    ]),
    post("Beach photo", INSTAGRAM, "2026-10-16T10:00:00Z", [
      metric("like_count", 5000),
      metric("comments_count", 4),
    ]),
  ]);
  api.analyticsContentTypes.set(project.id, SUMMARY);
}

async function openPage() {
  renderRoute(`/p/${project.id}/analytics`, { api });
  await screen.findByRole("heading", { level: 1, name: "Analytics" });
  return screen.findByLabelText("Account");
}

function titles(list: HTMLElement): string[] {
  return within(list)
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent ?? "");
}

describe("Analytics rankings and content types", () => {
  it("only ranks once one account is chosen, with its own metrics", async () => {
    seed();
    const user = userEvent.setup();
    const accountSelect = await openPage();

    const rankBy = screen.getByLabelText("Rank by");
    expect(rankBy).toBeDisabled();
    expect(
      screen.getByText(
        "Choose one account to rank its posts by one of its metrics.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/By content type/)).not.toBeInTheDocument();

    await user.selectOptions(accountSelect, "Instagram @cyber.ig");
    expect(rankBy).toBeEnabled();
    const instagramOptions = within(rankBy)
      .getAllByRole("option")
      .map((option) => option.textContent);
    // Insights (permission required) and engagement aren't offered for Instagram.
    expect(instagramOptions).toEqual([
      "Newest first (no ranking)",
      "Likes (like_count)",
      "Comments (comments_count)",
    ]);

    await user.selectOptions(accountSelect, "YouTube @cyber");
    expect(
      within(rankBy)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Newest first (no ranking)",
      "Views (viewCount)",
      "Likes (likeCount)",
      "Comments (commentCount)",
      "Engagement (calculated)",
    ]);
    const posts = await screen.findByRole("list", { name: "Published posts" });
    expect(titles(posts)).toEqual([
      "Few views",
      "Not read for views",
      "Many views",
    ]);
  });

  it("ranks one account by a metric and lists posts without it apart", async () => {
    seed();
    const user = userEvent.setup();
    const accountSelect = await openPage();
    await user.selectOptions(accountSelect, "YouTube @cyber");
    await user.selectOptions(screen.getByLabelText("Rank by"), "viewCount");

    const ranking = await screen.findByRole("list", {
      name: "Ranking by Views (viewCount)",
    });
    expect(titles(ranking)).toEqual(["#1 Many views", "#2 Few views"]);
    expect(
      screen.getByRole("heading", { name: "Top posts · YouTube @cyber" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/this ranking is not compared with other platforms/),
    ).toBeInTheDocument();
    const unranked = screen.getByRole("list", { name: "Not ranked" });
    expect(titles(unranked)).toEqual(["Not read for views"]);
    // Age and the reading date give context to every ranked post.
    const first = within(ranking).getAllByRole("listitem")[0];
    expect(within(first).getByText(/Published 4 days ago/)).toBeInTheDocument();
    expect(within(first).getByText(/Last valid update/)).toBeInTheDocument();
    expect(screen.queryByText("Beach photo")).not.toBeInTheDocument();
    const request = api.requests.findLast((r) => r.path.includes("/posts"));
    expect(request?.path).toContain("platform=youtube");
    expect(request?.path).toContain("account_id=1");
    expect(request?.path).toContain("sort=viewCount");

    // A real 0 is ranked.
    await user.selectOptions(screen.getByLabelText("Rank by"), "likeCount");
    const byLikes = await screen.findByRole("list", {
      name: "Ranking by Likes (likeCount)",
    });
    expect(titles(byLikes)).toEqual([
      "#1 Not read for views",
      "#2 Many views",
      "#3 Few views",
    ]);
  });

  it("filters by publication period, with an empty period", async () => {
    seed();
    const user = userEvent.setup();
    await openPage();

    await user.type(screen.getByLabelText("Published from"), "2026-10-17");
    await waitFor(() =>
      expect(
        titles(screen.getByRole("list", { name: "Published posts" })),
      ).toEqual(["Few views", "Not read for views"]),
    );
    expect(
      api.requests.findLast((r) => r.path.includes("/posts"))?.path,
    ).toContain("published_from=2026-10-17");

    await user.type(screen.getByLabelText("Published to"), "2026-10-01");
    expect(
      await screen.findByText("No posts published in this period."),
    ).toBeInTheDocument();
    // The filters stay available to change the period again.
    expect(screen.getByLabelText("Account")).toBeInTheDocument();
  });

  it("shows medians by content type and insufficient samples", async () => {
    seed();
    const user = userEvent.setup();
    const accountSelect = await openPage();
    await user.selectOptions(accountSelect, "YouTube @cyber");

    const types = await screen.findByRole("list", { name: "By content type" });
    const [video, image] = within(types).getAllByRole("listitem");
    expect(
      within(video).getByText(/3 of 4 posts with metrics/),
    ).toBeInTheDocument();
    expect(within(video).getByText(/median age 5 days/)).toBeInTheDocument();
    const views = within(video).getByText("viewCount").closest("div")!;
    expect(within(views).getByText("120")).toBeInTheDocument();
    const likes = within(video).getByText("likeCount").closest("div")!;
    expect(
      within(likes).getByText("Insufficient sample (2 posts, 3 needed)"),
    ).toBeInTheDocument();
    expect(within(video).getByText("4%")).toBeInTheDocument();

    expect(
      within(image).getByText(/Insufficient sample: fewer than 3 posts/),
    ).toBeInTheDocument();
    const request = api.requests.findLast((r) =>
      r.path.includes("/content-types"),
    );
    expect(request?.path).toContain("platform=youtube");
    expect(request?.path).toContain("account_id=1");
  });

  it("says when the account has no metrics to rank by", async () => {
    const tiktok: AccountCapability = {
      account_id: 3,
      platform: "tiktok",
      label: "TikTok @cyber",
      capability: { state: "not_supported", groups: [], reason: null },
    };
    api.analyticsAccounts.set(project.id, [tiktok]);
    api.analyticsPosts.set(project.id, [
      post("Inbox upload", tiktok, "2026-10-18T10:00:00Z", []),
    ]);
    api.analyticsContentTypes.set(project.id, []);
    const user = userEvent.setup();
    const accountSelect = await openPage();
    await user.selectOptions(accountSelect, "TikTok @cyber");

    expect(screen.getByLabelText("Rank by")).toBeDisabled();
    expect(
      await screen.findByText(
        "AutoPublisher reads no metrics of this account to rank by.",
      ),
    ).toBeInTheDocument();
  });
});
