import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type {
  MetricSeries,
  MetricSnapshotRead,
  PostAnalyticsRow,
  Project,
  PublicationAnalytics,
  RefreshState,
} from "../../types.ts";
import { formatDate } from "../../utils.ts";

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

const TIMES = [
  "2026-10-20T10:00:00Z",
  "2026-10-21T10:00:07Z",
  "2026-10-22T10:00:00Z",
  "2026-10-23T10:00:00Z",
];

function refresh(status: RefreshState["status"]): RefreshState {
  return {
    status,
    last_success_at: TIMES[3],
    last_attempt_at: TIMES[3],
    next_attempt_at: null,
    manual_pending: false,
    error_code: null,
    error_message: null,
    cooldown_until: null,
  };
}

function row(overrides: Partial<PostAnalyticsRow> = {}): PostAnalyticsRow {
  return {
    publication_id: 1,
    content_id: null,
    content_type: "text",
    title: "Summer teaser",
    platform: "youtube",
    account_id: 1,
    account_label: "YouTube @cyber",
    published_at: TIMES[0],
    age_days: 9,
    remote_url: null,
    link_state: "linked",
    not_linked_reason: null,
    capability_state: "supported",
    metrics: [],
    engagement: null,
    refresh: refresh("ok"),
    captured_at: TIMES[3],
    ranked: null,
    ...overrides,
  };
}

function snapshot(index: number): MetricSnapshotRead {
  return {
    snapshot_id: 10 + index,
    captured_at: TIMES[index],
    trigger: "automatic",
    source: "youtube.videos.list:statistics",
    remote_id: "VIDEO-1",
    values: [],
    engagement: null,
  };
}

function series(
  name: string,
  points: [number, number][],
  overrides: Partial<MetricSeries> = {},
): MetricSeries {
  return {
    name,
    label: name,
    concept: null,
    definition: `${name} as the platform reports it.`,
    derived: false,
    points: points.map(([reading, value]) => ({
      snapshot_id: 10 + reading,
      reading,
      captured_at: TIMES[reading],
      value,
    })),
    ...overrides,
  };
}

const YOUTUBE_HISTORY: Pick<PublicationAnalytics, "history" | "series"> = {
  history: [0, 1, 2, 3].map(snapshot),
  series: [
    series(
      "viewCount",
      [
        [0, 0],
        [1, 100],
        [2, 300],
        [3, 310],
      ],
      {
        concept: "views",
        definition:
          "Views of the video. Since 2026-08-24 YouTube counts Shorts views differently.",
      },
    ),
    // Comments disabled in the second reading: a gap, never 0.
    series(
      "commentCount",
      [
        [0, 0],
        [2, 1],
        [3, 1],
      ],
      { concept: "comments" },
    ),
    series(
      "engagement",
      [
        [2, 10 / 300],
        [3, 10 / 310],
      ],
      { derived: true, definition: "Calculated by AutoPublisher per reading." },
    ),
  ],
};

async function openEvolution(
  history: Pick<PublicationAnalytics, "history" | "series">,
  overrides: Partial<PostAnalyticsRow> = {},
) {
  api.analyticsPosts.set(project.id, [row(overrides)]);
  api.analyticsHistory.set(1, history);
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/analytics`, { api });
  const card = await screen.findByRole("listitem", { name: "Summer teaser" });
  await user.click(within(card).getByRole("button", { name: "Evolution" }));
  return { user, card };
}

function chart(): SVGElement {
  return screen.getByRole("img", {
    name: /real reading/,
  }) as unknown as SVGElement;
}

describe("Post evolution", () => {
  it("draws exactly the real readings, in time order, with exact values", async () => {
    const { card } = await openEvolution(YOUTUBE_HISTORY);

    await within(card).findByLabelText("Metric");
    const svg = chart();
    expect(svg.querySelectorAll(".ap-analytics__chart-dot")).toHaveLength(4);
    expect(svg.querySelectorAll(".ap-analytics__chart-link")).toHaveLength(3);
    expect(svg.querySelectorAll(".ap-analytics__chart-tick")).toHaveLength(4);
    const xs = [...svg.querySelectorAll(".ap-analytics__chart-dot")].map(
      (dot) => Number(dot.getAttribute("cx")),
    );
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    const rows = within(within(card).getByRole("table")).getAllByRole("row");
    expect(rows.slice(1).map((r) => r.textContent)).toEqual([
      `${formatDate(TIMES[0])}0`,
      `${formatDate(TIMES[1])}100`,
      `${formatDate(TIMES[2])}300`,
      `${formatDate(TIMES[3])}310`,
    ]);
    expect(within(card).getByText(/4 of 4 readings have/)).toBeInTheDocument();
    // The YouTube views definition note is shown with the chart.
    expect(within(card).getByText(/Since 2026-08-24/)).toBeInTheDocument();
  });

  it("leaves a gap for a reading without the metric (no 0, no line)", async () => {
    const { user, card } = await openEvolution(YOUTUBE_HISTORY);
    await user.selectOptions(
      await within(card).findByLabelText("Metric"),
      "commentCount",
    );

    const svg = chart();
    const dots = [...svg.querySelectorAll(".ap-analytics__chart-dot")];
    expect(dots.map((dot) => dot.getAttribute("data-reading"))).toEqual([
      "0",
      "2",
      "3",
    ]);
    // Only readings 2→3 are consecutive; 0→2 skips the reading without it.
    expect(svg.querySelectorAll(".ap-analytics__chart-link")).toHaveLength(1);
    expect(svg.querySelectorAll(".ap-analytics__chart-tick")).toHaveLength(4);
    const table = within(card).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).queryByText(formatDate(TIMES[1]))).toBeNull();
    expect(within(card).getByText(/3 of 4 readings have/)).toBeInTheDocument();
  });

  it("offers only metrics seen at least once, engagement per reading", async () => {
    const { user, card } = await openEvolution(YOUTUBE_HISTORY);
    const select = await within(card).findByLabelText("Metric");

    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "Views (viewCount)",
      "Comments (commentCount)",
      "Engagement (calculated)",
    ]);
    await user.selectOptions(select, "engagement");
    const table = within(card).getByRole("table");
    expect(within(table).getByText("3.33%")).toBeInTheDocument();
    expect(within(table).getByText("3.23%")).toBeInTheDocument();
  });

  it("shows a single reading without a line", async () => {
    const { card } = await openEvolution({
      history: [snapshot(0)],
      series: [series("like_count", [[0, 15]], { concept: "likes" })],
    });

    expect(
      await within(card).findByText(/Only one reading so far/),
    ).toBeInTheDocument();
    const svg = chart();
    expect(svg.querySelectorAll(".ap-analytics__chart-dot")).toHaveLength(1);
    expect(svg.querySelectorAll(".ap-analytics__chart-link")).toHaveLength(0);
  });

  it("explains a post with no readings", async () => {
    const { card } = await openEvolution(
      { history: [], series: [] },
      { captured_at: null, refresh: refresh("pending") },
    );

    expect(
      await within(card).findByText(/No readings yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /real reading/ })).toBeNull();
  });

  it("keeps the saved history when the post can't be updated now", async () => {
    const { card } = await openEvolution(YOUTUBE_HISTORY, {
      refresh: refresh("remote_deleted"),
    });

    expect(
      within(card).getByText("Deleted on the platform"),
    ).toBeInTheDocument();
    await within(card).findByLabelText("Metric");
    expect(chart().querySelectorAll(".ap-analytics__chart-dot")).toHaveLength(
      4,
    );
    expect(api.requests.at(-1)?.path).toBe("/publications/1/analytics");
  });
});
