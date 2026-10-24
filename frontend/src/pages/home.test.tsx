import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import { renderRoute } from "../test-utils.tsx";
import type {
  AccountHealth,
  AccountHealthState,
  AttentionItem,
  PlatformAvailability,
  PostDisplayState,
  AttentionTarget,
  Overview,
  UpcomingPost,
} from "../types.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.unstubAllGlobals();
});

const FUTURE = "2099-01-01T10:00:00Z";
const ACCOUNT = {
  id: 4,
  platform: "instagram" as const,
  label: "Instagram @l4i4",
};

// Fixtures are already-derived read-models: the tests never re-derive attention.
function attention(
  title: string,
  label: string,
  target: AttentionTarget,
  overrides: Partial<AttentionItem> = {},
): AttentionItem {
  return {
    kind: "failed",
    priority: 2,
    project: { id: 1, name: "Cyber" },
    account: ACCOUNT,
    post: null,
    title,
    detail: null,
    at: null,
    action: { label, target },
    affected_posts: 0,
    ...overrides,
  };
}

function upcoming(id: number): UpcomingPost {
  return {
    post_id: id,
    project: { id: 1, name: "Cyber" },
    account: ACCOUNT,
    scheduled_at: FUTURE,
    display_state: "scheduled_automatic",
    media_title: `Episode ${id}`,
    excerpt: null,
  };
}

/** Two projects ("Cyber" with problems, inactive "Studio") and an overview. */
function seed(overview: Partial<Overview> = {}): Overview {
  const cyber = api.addProject({ name: "Cyber" });
  const studio = api.addProject({ name: "Studio", is_active: false });
  const base = api.emptyOverview();
  base.projects[0].attention_count = 2;
  base.projects[0].next_post = {
    post_id: 1,
    scheduled_at: FUTURE,
    display_state: "scheduled_automatic",
  };
  api.overview = { ...base, ...overview };
  expect([cyber.id, studio.id]).toEqual([1, 2]);
  return api.overview;
}

function overviewRequests() {
  return api.requests
    .filter((request) => request.path.startsWith("/overview"))
    .map((request) => request.path);
}

describe("Home", () => {
  it("lists what needs attention, in order, with one action each", async () => {
    seed({
      attention: [
        attention(
          "Check Instagram before retrying",
          "Review",
          {
            type: "post",
            project_id: 1,
            id: 12,
          },
          {
            kind: "manual_review",
            detail: "This post may have published.",
            post: {
              id: 12,
              display_state: "needs_review",
              scheduled_at: null,
              media_title: "Launch teaser",
              excerpt: null,
            },
          },
        ),
        attention(
          "Reconnect needed",
          "Reconnect",
          {
            type: "account",
            project_id: 1,
            id: 4,
          },
          { kind: "reconnect", affected_posts: 3 },
        ),
        attention(
          "Automation is paused",
          "Open Settings",
          { type: "settings" },
          {
            kind: "missed",
          },
        ),
      ],
    });
    renderRoute("/");

    const section = await screen.findByRole("region", {
      name: /Needs attention/,
    });
    const items = within(section).getAllByRole("listitem");
    expect(
      items.map((item) => within(item).getByRole("heading").textContent),
    ).toEqual([
      "Check Instagram before retrying",
      "Reconnect needed",
      "Automation is paused",
    ]);
    const expected = [
      ["Review", "/p/1/posts/12"],
      ["Reconnect", "/p/1/accounts/4"],
      ["Open Settings", "/settings"],
    ];
    items.forEach((item, index) => {
      const links = within(item).getAllByRole("link");
      expect(links).toHaveLength(1);
      expect(links[0]).toHaveAccessibleName(expected[index][0]);
      expect(links[0]).toHaveAttribute("href", expected[index][1]);
      expect(within(item).queryByRole("button")).not.toBeInTheDocument();
    });
    expect(items[0]).toHaveTextContent("This post may have published.");
    expect(items[0]).toHaveTextContent(
      "Cyber · Instagram @l4i4 · Launch teaser",
    );
    expect(within(items[0]).getByText("Needs review")).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("3 scheduled posts affected");
    expect(screen.queryByText("Everything looks good")).not.toBeInTheDocument();
    expect(overviewRequests()).toEqual(["/overview"]);
  });

  it("shows Everything looks good, at most five upcoming posts and the projects", async () => {
    seed({ upcoming: [1, 2, 3, 4, 5, 6].map(upcoming) });
    renderRoute("/");

    expect(
      await screen.findByRole("heading", { name: "Everything looks good" }),
    ).toBeInTheDocument();
    const upNext = screen.getByRole("region", { name: "Up next" });
    const rows = within(upNext).getAllByRole("link");
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveAttribute("href", "/p/1/posts/1");
    expect(rows[0]).toHaveTextContent("Episode 1");
    expect(rows[0]).toHaveTextContent("Scheduled · automatic");
    expect(within(upNext).queryByText(/See more/)).not.toBeInTheDocument();

    const projects = screen.getByRole("region", { name: "Projects" });
    const [cyber, studio] = within(projects).getAllByRole("link");
    expect(cyber).toHaveAttribute("href", "/p/1/library");
    expect(cyber).toHaveTextContent("2 need attention");
    expect(cyber).toHaveTextContent("Next:");
    expect(studio).toHaveTextContent("Inactive");
    expect(studio).toHaveTextContent("All good");
    expect(studio).toHaveTextContent("Nothing scheduled");
  });

  it("explains a global pause and links to Settings without a toggle", async () => {
    const overview = seed();
    overview.automation = {
      paused: true,
      running: true,
      paused_automatic_posts: 2,
    };
    renderRoute("/");

    const banner = await screen.findByRole("region", {
      name: "Automatic publishing is paused",
    });
    expect(banner).toHaveTextContent("2 scheduled posts won't publish");
    expect(
      within(banner).getByRole("link", { name: "Go to Settings" }),
    ).toHaveAttribute("href", "/settings");
    expect(
      screen.queryByRole("button", { name: /Pause|Resume/ }),
    ).not.toBeInTheDocument();
  });

  it("filters by project on the server and shows all again", async () => {
    seed();
    const filtered = api.emptyOverview([api.projects[1]]);
    api.projectOverviews.set(2, filtered);
    const user = userEvent.setup();
    const { router } = renderRoute("/?project=2");

    expect(
      await screen.findByText("Studio", { selector: "strong" }),
    ).toBeInTheDocument();
    expect(overviewRequests()).toEqual(["/overview?project_id=2"]);
    expect(
      within(screen.getByRole("region", { name: "Projects" })).getAllByRole(
        "link",
      ),
    ).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: "New project" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Show all projects" }));
    expect(router.state.location.search).toBe("");
    await screen.findByRole("button", { name: "New project" });
    expect(overviewRequests()).toEqual(["/overview?project_id=2", "/overview"]);
  });

  it.each(["/?project=99", "/?project=abc"])(
    "explains a missing project at %s",
    async (path) => {
      seed();
      renderRoute(path);

      expect(
        await screen.findByRole("heading", {
          name: "This project doesn't exist",
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Show all projects" }),
      ).toHaveAttribute("href", "/");
      expect(
        screen.queryByText("Everything looks good"),
      ).not.toBeInTheDocument();
    },
  );

  it("shows a skeleton while loading and Retry after an error, never a false OK", async () => {
    seed();
    api.overviewFailures.push({
      status: 500,
      body: {
        error: { code: "internal", message: "The server had a problem." },
      },
    });
    const user = userEvent.setup();
    const release = api.holdRequest("GET", "/overview");
    renderRoute("/");

    // After the session bootstrap (Feature 020) the overview starts loading.
    expect(await screen.findByText("Loading overview…")).toBeInTheDocument();
    expect(screen.queryByText("Everything looks good")).not.toBeInTheDocument();
    release();
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Couldn't load the overview");
    expect(screen.queryByText("Everything looks good")).not.toBeInTheDocument();

    await user.click(within(error).getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "Everything looks good" }),
    ).toBeInTheDocument();
  });

  it("offers only Create project without projects and lands on its Library", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/");

    await screen.findByRole("heading", { name: "Create your first project" });
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("button")).toHaveLength(1);
    expect(
      screen.queryByRole("region", { name: "Up next" }),
    ).not.toBeInTheDocument();

    await user.click(
      within(main).getByRole("button", { name: "Create project" }),
    );
    const dialog = screen.getByRole("dialog", { name: "New project" });
    await user.type(within(dialog).getByLabelText("Name"), "L4i4");
    await act(() =>
      user.click(
        within(dialog).getByRole("button", { name: "Create project" }),
      ),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Library" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/p/1/library");
  });

  it("speaks product language on Home, Accounts and Settings", async () => {
    const states: PostDisplayState[] = [
      "draft",
      "scheduled_automatic",
      "scheduled_manual",
      "scheduled_paused",
      "publishing",
      "published",
      "failed",
      "needs_review",
      "needs_action",
      "missed",
      "cancelled",
    ];
    seed({
      attention: states.map((state, index) =>
        attention(
          `Item ${index}`,
          "Open",
          { type: "post", project_id: 1, id: index + 1 },
          {
            post: {
              id: index + 1,
              display_state: state,
              scheduled_at: FUTURE,
              media_title: `Media ${index}`,
              excerpt: null,
            },
          },
        ),
      ),
      upcoming: (
        ["scheduled_automatic", "scheduled_manual", "scheduled_paused"] as const
      ).map((state, index) => ({
        ...upcoming(index + 1),
        display_state: state,
      })),
    });
    const accountStates: AccountHealthState[] = [
      "ready",
      "reconnect_needed",
      "setup_required",
      "not_connected",
      "inactive",
    ];
    api.accountHealth.set(
      1,
      accountStates.map((state, index): AccountHealth => {
        const account = api.addAccount({
          project_id: 1,
          platform: "youtube",
          handle: `a${index}`,
        });
        return {
          account_id: account.id,
          platform: "youtube",
          label: `YouTube @a${index}`,
          display_name: null,
          is_active: state !== "inactive",
          state,
          identity: null,
          expires_at: null,
          expiring: false,
          capabilities: ["videos"],
          issue: null,
          can_discard: false,
        };
      }),
    );
    api.platforms = (
      ["configured", "partial", "not_configured", "coming_soon"] as const
    ).map((status, index): PlatformAvailability => ({
      platform: (["youtube", "instagram", "tiktok", "x"] as const)[index],
      label: ["YouTube", "Instagram", "TikTok", "X"][index],
      integration_available: status !== "coming_soon",
      status,
      can_connect: status === "configured" || status === "partial",
      missing: [],
      message: null,
    }));

    /** Visible product text; technical <details> may use technical words. */
    function visibleText() {
      const main = screen.getByRole("main").cloneNode(true) as HTMLElement;
      main.querySelectorAll("details").forEach((details) => details.remove());
      return main.textContent ?? "";
    }
    const FORBIDDEN =
      /\b(publications?|assets?|queue|prepare|unscheduled|preflight|reconcile|attempts?|checksum)\b|_/i;

    renderRoute("/");
    await screen.findByRole("region", { name: /Needs attention/ });
    for (const label of [
      "Draft",
      "Scheduled · automatic",
      "Scheduled · manual",
      "Scheduled · paused",
      "Publishing",
      "Published",
      "Failed",
      "Needs review",
      "Needs action",
      "Missed",
      "Cancelled",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(visibleText()).not.toMatch(FORBIDDEN);
    expect(visibleText()).not.toMatch(
      /Scheduled(?! · (automatic|manual|paused))/,
    );
    cleanup();

    renderRoute("/p/1/accounts");
    await screen.findByRole("list", { name: "Accounts" });
    for (const label of [
      "Ready",
      "Reconnect needed",
      "Finish setup",
      "Not connected",
      "Inactive",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(visibleText()).not.toMatch(FORBIDDEN);
    cleanup();

    renderRoute("/settings");
    await screen.findByRole("list", { name: "Platform integrations" });
    for (const label of [
      "Configured",
      "Partially configured",
      "Not configured",
      "Coming soon",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(visibleText()).not.toMatch(FORBIDDEN);
  });
});
