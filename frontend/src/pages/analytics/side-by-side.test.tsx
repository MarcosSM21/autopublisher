import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type {
  AlignedCell,
  ContentSideBySide,
  MetricValue,
  Project,
  PublicationAnalyticsRead,
  RefreshState,
} from "../../types.ts";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const READ = "2026-10-20T10:00:00Z";
const CONTENT_ID = 7;
const NOTE =
  "Not quantitatively equivalent across platforms: each platform counts in its own way, so these values are shown next to each other, never compared.";

function metric(name: string, value: number | null): MetricValue {
  return {
    name,
    label: name,
    value,
    available: value !== null,
    origin: "public_counter",
    concept: name === "viewCount" ? "views" : null,
    definition: `${name} as the platform reports it.`,
  };
}

function refresh(overrides: Partial<RefreshState> = {}): RefreshState {
  return {
    status: "ok",
    last_success_at: READ,
    last_attempt_at: READ,
    next_attempt_at: null,
    manual_pending: false,
    error_code: null,
    error_message: null,
    cooldown_until: null,
    ...overrides,
  };
}

function publication(
  overrides: Partial<PublicationAnalyticsRead>,
): PublicationAnalyticsRead {
  return {
    publication_id: 1,
    content_id: CONTENT_ID,
    content_type: "video",
    title: "Summer teaser",
    platform: "youtube",
    account_id: 1,
    account_label: "YouTube @cyber",
    published_at: READ,
    age_days: 3,
    remote_url: null,
    link_state: "linked",
    not_linked_reason: null,
    capability_state: "supported",
    metrics: [],
    engagement: null,
    refresh: refresh(),
    captured_at: READ,
    ...overrides,
  };
}

const YOUTUBE = publication({
  publication_id: 1,
  remote_url: "https://youtu.be/VIDEO1",
  metrics: [metric("viewCount", 500), metric("dislikeCount", 2)],
  engagement: {
    available: true,
    value: 0.014,
    formula: "(likeCount + commentCount) / viewCount",
    components: { likeCount: 0, commentCount: 7, viewCount: 500 },
  },
});
const INSTAGRAM = publication({
  publication_id: 2,
  platform: "instagram",
  account_id: 2,
  account_label: "Instagram @cyber.ig",
  age_days: 2,
  refresh: refresh({ status: "stale", error_code: "refresh_failed" }),
});
const TIKTOK = publication({
  publication_id: 3,
  platform: "tiktok",
  account_id: 3,
  account_label: "TikTok @cyber.tt",
  capability_state: "not_supported",
  refresh: null,
  captured_at: null,
});
const UNLINKED = publication({
  publication_id: 4,
  platform: "instagram",
  account_id: 4,
  account_label: "Instagram @other",
  link_state: "not_linked",
  not_linked_reason: "remote_identity_changed",
  refresh: null,
  captured_at: null,
});

function cell(
  row: PublicationAnalyticsRead,
  metricName: string | null,
  value: number | null,
): AlignedCell {
  return {
    publication_id: row.publication_id,
    platform: row.platform,
    account_id: row.account_id,
    metric_name: metricName,
    value,
    available: value !== null,
    definition: metricName ? `${metricName} as the platform reports it.` : null,
  };
}

function view(
  perPlatform: PublicationAnalyticsRead[],
  aligned: ContentSideBySide["aligned"],
): ContentSideBySide {
  return {
    content_id: CONTENT_ID,
    aligned,
    per_platform: perPlatform,
    note: NOTE,
  };
}

const FULL = view(
  [YOUTUBE, INSTAGRAM, TIKTOK, UNLINKED],
  [
    {
      concept: "likes",
      label: "Likes",
      definition: "How many people liked the post on its platform.",
      cells: [
        cell(YOUTUBE, "likeCount", 0),
        // Instagram hid the likes of this post.
        cell(INSTAGRAM, "like_count", null),
        cell(TIKTOK, null, null),
        cell(UNLINKED, "like_count", null),
      ],
    },
    {
      concept: "comments",
      label: "Comments",
      definition: "How many comments or replies the post received.",
      cells: [
        cell(YOUTUBE, "commentCount", 7),
        cell(INSTAGRAM, "comments_count", 4000),
        cell(TIKTOK, null, null),
        cell(UNLINKED, "comments_count", null),
      ],
    },
  ],
);

async function openView(content: ContentSideBySide | null) {
  if (content) api.contentAnalytics.set(CONTENT_ID, content);
  renderRoute(`/p/${project.id}/analytics/media/${CONTENT_ID}`, { api });
  await screen.findByRole("heading", { level: 1, name: "Media side by side" });
}

function alignedRow(label: string): HTMLElement {
  return screen.getByRole("region", { name: label });
}

function cellFor(row: HTMLElement, account: string): HTMLElement {
  return within(row).getByText(account).closest(".ap-analytics__cell")!;
}

describe("Media side by side", () => {
  it("lines up likes and comments with their original names and the note", async () => {
    await openView(FULL);

    expect(await screen.findByRole("note")).toHaveTextContent(
      "Not quantitatively equivalent across platforms",
    );
    const likes = alignedRow("Likes");
    expect(
      within(cellFor(likes, "YouTube @cyber")).getByText("likeCount"),
    ).toBeInTheDocument();
    // A real 0 next to hidden likes ("Not available", never 0).
    expect(
      within(cellFor(likes, "YouTube @cyber")).getByText("0"),
    ).toBeVisible();
    expect(
      within(cellFor(likes, "Instagram @cyber.ig")).getByText("like_count"),
    ).toBeInTheDocument();
    expect(
      within(cellFor(likes, "Instagram @cyber.ig")).getByText("Not available"),
    ).toBeInTheDocument();
    expect(
      within(cellFor(likes, "TikTok @cyber.tt")).getByText(
        "No metric for this on TikTok",
      ),
    ).toBeInTheDocument();
    const comments = alignedRow("Comments");
    expect(
      within(cellFor(comments, "Instagram @cyber.ig")).getByText("4,000"),
    ).toBeInTheDocument();
  });

  it("never marks, orders or totals the aligned values", async () => {
    await openView(FULL);
    const comments = await screen.findByRole("region", { name: "Comments" });

    // Served account order, even though Instagram's value is larger.
    const cells = comments.querySelectorAll(".ap-analytics__cell");
    expect([...cells].map((c) => c.querySelector("dt")?.textContent)).toEqual([
      "YouTube @cyber commentCount",
      "Instagram @cyber.ig comments_count",
      "TikTok @cyber.tt",
      "Instagram @other comments_count",
    ]);
    // Every cell looks the same: no highlight class on the larger value.
    expect(new Set([...cells].map((c) => c.className))).toEqual(
      new Set(["ap-analytics__cell"]),
    );
    const aligned = screen.getByRole("region", { name: "Shown side by side" });
    expect(aligned.textContent).not.toMatch(
      /total|sum|average|best|winner|more|less|higher|lower|difference|%|#\d/i,
    );
    expect(document.body.textContent).not.toMatch(
      /total|average|best|winner|overall/i,
    );
  });

  it("keeps views, engagement and other metrics inside their own publication", async () => {
    await openView(FULL);
    const each = await screen.findByRole("list", { name: "Each publication" });
    const youtube = within(each).getByRole("listitem", {
      name: "YouTube @cyber",
    });
    expect(within(youtube).getByText("viewCount")).toBeInTheDocument();
    expect(within(youtube).getAllByText("dislikeCount").length).toBeGreaterThan(
      0,
    );
    expect(within(youtube).getByText("1.4%")).toBeInTheDocument();
    expect(
      within(youtube).getByText("(likeCount + commentCount) / viewCount"),
    ).toBeInTheDocument();
    expect(
      within(youtube).getByRole("link", { name: /Open on YouTube/ }),
    ).toHaveAttribute("href", "https://youtu.be/VIDEO1");
    const aligned = screen.getByRole("region", { name: "Shown side by side" });
    expect(within(aligned).queryByText("viewCount")).not.toBeInTheDocument();
    expect(within(aligned).queryByText(/Engagement/)).not.toBeInTheDocument();
    expect(screen.getAllByText("viewCount")).toHaveLength(1);
  });

  it("explains publications without data, stale and not linked", async () => {
    await openView(FULL);
    const each = await screen.findByRole("list", { name: "Each publication" });

    const instagram = within(each).getByRole("listitem", {
      name: "Instagram @cyber.ig",
    });
    expect(within(instagram).getByText("Out of date")).toBeInTheDocument();
    expect(
      within(instagram).getByText(/Last valid update/),
    ).toBeInTheDocument();
    const tiktok = within(each).getByRole("listitem", {
      name: "TikTok @cyber.tt",
    });
    expect(
      within(tiktok).getByText(
        "AutoPublisher doesn't read this platform's metrics in this version.",
      ),
    ).toBeInTheDocument();
    const unlinked = within(each).getByRole("listitem", {
      name: "Instagram @other",
    });
    expect(
      within(unlinked).getByText(/Published by another account/),
    ).toBeInTheDocument();
    expect(within(unlinked).getByText("Never read.")).toBeInTheDocument();
  });

  it("shows a single publication and an unpublished media", async () => {
    await openView(
      view(
        [INSTAGRAM],
        [
          {
            concept: "likes",
            label: "Likes",
            definition: "Likes.",
            cells: [cell(INSTAGRAM, "like_count", 9)],
          },
        ],
      ),
    );
    expect(
      await screen.findByText(/Published on one account only/),
    ).toBeInTheDocument();
    cleanup();

    await openView(view([], []));
    expect(
      await screen.findByText(/hasn't been published yet/),
    ).toBeInTheDocument();
  });

  it("reports a missing media", async () => {
    await openView(null);
    expect(
      await screen.findByText("Couldn't load this media's metrics"),
    ).toBeInTheDocument();
  });

  it("opens from a media post in Analytics", async () => {
    api.analyticsPosts.set(project.id, [
      { ...YOUTUBE, title: "Summer teaser", ranked: null },
      {
        ...YOUTUBE,
        publication_id: 9,
        content_id: null,
        content_type: "text",
        title: "Text only",
        ranked: null,
      },
    ]);
    api.contentAnalytics.set(CONTENT_ID, FULL);
    const user = userEvent.setup();
    renderRoute(`/p/${project.id}/analytics`, { api });

    const text = await screen.findByRole("listitem", { name: "Text only" });
    // A text post has no media to group by.
    expect(
      within(text).queryByRole("link", { name: /Side by side/ }),
    ).not.toBeInTheDocument();
    const media = screen.getByRole("listitem", { name: "Summer teaser" });
    await user.click(within(media).getByRole("link", { name: /Side by side/ }));

    expect(
      await screen.findByRole("heading", { name: "Media side by side" }),
    ).toBeInTheDocument();
    expect(api.requests.at(-1)?.path).toBe(`/contents/${CONTENT_ID}/analytics`);
  });
});
