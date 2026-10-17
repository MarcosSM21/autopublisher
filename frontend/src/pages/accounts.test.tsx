import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POLL_INTERVAL_MS } from "../components/YouTubeConnectionPanel.tsx";
import { FakeApi } from "../test-fake-api.ts";
import { renderRoute } from "../test-utils.tsx";
import type {
  Account,
  AccountHealth,
  PlatformAvailability,
  Project,
} from "../types.ts";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function setViewport(width: number) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: width >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

/** Already-derived health for an account (the fake never derives it). */
function health(
  account: Account,
  overrides: Partial<AccountHealth> = {},
): AccountHealth {
  return {
    account_id: account.id,
    platform: account.platform,
    label: `${account.platform} @${account.handle}`,
    display_name: account.display_name,
    is_active: account.is_active,
    state: "ready",
    identity: {
      name: "Cyber Studio",
      username: account.handle,
      avatar_url: null,
    },
    expires_at: null,
    expiring: false,
    capabilities: ["images", "videos"],
    issue: null,
    can_discard: false,
    ...overrides,
  };
}

const PLATFORMS: PlatformAvailability[] = [
  {
    platform: "youtube",
    label: "YouTube",
    integration_available: true,
    status: "configured",
    can_connect: true,
    missing: [],
    message: null,
  },
  {
    platform: "instagram",
    label: "Instagram",
    integration_available: true,
    status: "configured",
    can_connect: true,
    missing: [],
    message: null,
  },
  {
    platform: "threads",
    label: "Threads",
    integration_available: true,
    status: "configured",
    can_connect: true,
    missing: [],
    message: null,
  },
  {
    platform: "telegram",
    label: "Telegram",
    integration_available: true,
    status: "configured",
    can_connect: true,
    missing: [],
    message: null,
  },
  {
    platform: "tiktok",
    label: "TikTok",
    integration_available: true,
    status: "not_configured",
    can_connect: false,
    missing: ["app_credentials"],
    message: null,
  },
  {
    platform: "x",
    label: "X",
    integration_available: false,
    status: "coming_soon",
    can_connect: false,
    missing: [],
    message: null,
  },
];

function cards() {
  return within(screen.getByRole("list", { name: "Accounts" })).getAllByRole(
    "listitem",
  );
}

describe("Accounts", () => {
  it("without accounts offers only Connect an account", async () => {
    renderRoute(`/p/${project.id}/accounts`);

    await screen.findByRole("heading", { name: "Connect an account" });
    const main = screen.getByRole("main");
    const actions = within(main)
      .getAllByRole("link")
      .filter((link) => /account/i.test(link.textContent ?? ""));
    expect(actions).toHaveLength(1);
    expect(actions[0]).toHaveAccessibleName("Connect an account");
    expect(actions[0]).toHaveAttribute("href", `/p/${project.id}/accounts/new`);
  });

  it("shows each state in product words with at most one action", async () => {
    const make = (platform: Account["platform"], handle: string | null) =>
      api.addAccount({ project_id: project.id, platform, handle });
    const ready = make("youtube", "ready");
    const reconnect = make("instagram", "lost");
    const setup = make("telegram", "chan");
    const provisional = make("threads", null);
    const expiring = make("tiktok", "soon");
    api.accountHealth.set(project.id, [
      health(ready),
      health(reconnect, {
        state: "reconnect_needed",
        issue: {
          code: "x",
          message: "Instagram no longer accepts the saved login.",
        },
      }),
      health(setup, {
        state: "setup_required",
        issue: { code: "x", message: "Choose a channel to publish to." },
      }),
      health(provisional, {
        state: "not_connected",
        identity: null,
        can_discard: true,
      }),
      health(expiring, {
        expiring: true,
        issue: { code: "x", message: "The TikTok login expires in 3 days." },
      }),
    ]);
    renderRoute(`/p/${project.id}/accounts`);
    await screen.findByRole("list", { name: "Accounts" });

    const expected = [
      ["Ready", "Details"],
      ["Reconnect needed", "Reconnect"],
      ["Finish setup", "Finish setup"],
      ["Not connected", "Connect"],
      ["Ready", "Reconnect"],
    ];
    cards().forEach((card, index) => {
      expect(card).toHaveTextContent(expected[index][0]);
      const links = within(card).getAllByRole("link");
      expect(links).toHaveLength(1);
      expect(links[0]).toHaveTextContent(expected[index][1]);
      expect(card.textContent).not.toMatch(
        /reconnect_needed|setup_required|not_connected/,
      );
    });
    expect(cards()[3]).toHaveTextContent("Threads Not connected yet");
    expect(cards()[0]).toHaveTextContent("Images · Videos");
  });

  it("keeps technical details closed when ready and opens them to reconnect", async () => {
    const ready = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "ok",
    });
    const lost = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "lost",
    });
    api.accountHealth.set(project.id, [
      health(ready),
      health(lost, { state: "reconnect_needed" }),
    ]);
    renderRoute(`/p/${project.id}/accounts/${ready.id}`);

    let details = (
      await screen.findByText("Connection & technical details")
    ).closest("details")!;
    expect(details).not.toHaveAttribute("open");
    // The panel is mounted even while closed (its polling must not stop).
    expect(
      await within(details).findByRole("group", {
        name: "YouTube connection of @ok",
        hidden: true,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Discard setup" }),
    ).not.toBeInTheDocument();
    cleanup();

    renderRoute(`/p/${project.id}/accounts/${lost.id}`);
    details = (
      await screen.findByText("Connection & technical details")
    ).closest("details")!;
    expect(details).toHaveAttribute("open");
  });

  it("confirms a saved name", async () => {
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "ok",
    });
    api.accountHealth.set(project.id, [health(account)]);
    const user = userEvent.setup();
    renderRoute(`/p/${project.id}/accounts/${account.id}`);

    await user.type(
      await screen.findByLabelText("Name in AutoPublisher"),
      "Main channel",
    );
    await user.click(screen.getByRole("button", { name: "Save name" }));

    expect(await screen.findByText("Name saved.")).toBeInTheDocument();
    expect(api.requests).toContainEqual(
      expect.objectContaining({
        method: "PATCH",
        body: { display_name: "Main channel" },
      }),
    );
  });

  it.each([
    ["abc", "a non-numeric id"],
    ["999", "a missing account"],
    ["other", "an account of another project"],
  ])("shows not found for %s (%s)", async (id) => {
    const other = api.addProject({ name: "Other" });
    const foreign = api.addAccount({
      project_id: other.id,
      platform: "youtube",
    });
    renderRoute(
      `/p/${project.id}/accounts/${id === "other" ? foreign.id : id}`,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Not found" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to Accounts" }),
    ).toHaveAttribute("href", `/p/${project.id}/accounts`);
  });

  it("discards an abandoned setup after confirming", async () => {
    const provisional = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: null,
    });
    const user = userEvent.setup();
    const { router } = renderRoute(
      `/p/${project.id}/accounts/${provisional.id}`,
    );

    await user.click(
      await screen.findByRole("button", { name: "Discard setup" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Discard this setup?" });
    await user.click(
      within(dialog).getByRole("button", { name: "Discard setup" }),
    );

    expect(router.state.location.pathname).toBe(`/p/${project.id}/accounts`);
    expect(api.requests).toContainEqual(
      expect.objectContaining({
        method: "DELETE",
        path: `/accounts/${provisional.id}`,
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "Connect an account" }),
    ).toBeInTheDocument();
  });

  it("lists platforms: X is not selectable, a missing setup points to Settings", async () => {
    api.platforms = PLATFORMS;
    const user = userEvent.setup();
    renderRoute(`/p/${project.id}/accounts/new`);

    const sheet = await screen.findByRole("dialog", { name: "Add account" });
    await within(sheet).findByRole("radio", { name: /YouTube/ });
    expect(within(sheet).getByRole("radio", { name: /X/ })).toBeDisabled();
    expect(within(sheet).getByText("Coming soon")).toBeInTheDocument();

    await user.click(within(sheet).getByRole("radio", { name: /TikTok/ }));
    expect(
      within(sheet).getByText("AutoPublisher isn't set up for TikTok yet."),
    ).toBeInTheDocument();
    expect(
      within(sheet).getByRole("link", { name: "Open Settings" }),
    ).toHaveAttribute("href", "/settings");
    expect(
      within(sheet).queryByRole("button", { name: /^Connect/ }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["youtube", "YouTube"],
    ["instagram", "Instagram"],
    ["threads", "Threads"],
    ["telegram", "Telegram"],
  ] as const)(
    "Set up %s creates a provisional account and opens its URL with the panel",
    async (platform, label) => {
      api.platforms = PLATFORMS;
      const user = userEvent.setup();
      const { router } = renderRoute(`/p/${project.id}/accounts/new`);
      const sheet = await screen.findByRole("dialog", { name: "Add account" });

      await user.click(
        await within(sheet).findByRole("radio", { name: new RegExp(label) }),
      );
      await user.click(
        within(sheet).getByRole("button", { name: `Set up ${label}` }),
      );

      expect(api.requests).toContainEqual(
        expect.objectContaining({
          method: "POST",
          path: `/projects/${project.id}/accounts`,
          body: { platform },
        }),
      );
      const created = api.accounts.at(-1)!;
      expect(created.handle).toBeNull();
      expect(router.state.location.pathname).toBe(
        `/p/${project.id}/accounts/${created.id}`,
      );
      expect(
        await screen.findByRole("group", {
          name: `${label} connection of ${label} account`,
        }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("dialog", { name: "Add account" }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Discard setup" }),
      ).toBeInTheDocument();
    },
  );

  it("keeps the setup after a reload, without the Add sheet", async () => {
    const provisional = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: null,
    });
    renderRoute(`/p/${project.id}/accounts/${provisional.id}`);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "YouTube Not connected yet",
      }),
    ).toBeInTheDocument();
    const details = screen
      .getByText("Connection & technical details")
      .closest("details")!;
    expect(details).toHaveAttribute("open");
    expect(
      await within(details).findByRole("group", {
        name: "YouTube connection of YouTube account",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Discard setup" }),
    ).toBeInTheDocument();
    // No competing "Connect an account" (it would create a second account).
    expect(
      screen.queryByRole("link", { name: "Connect an account" }),
    ).not.toBeInTheDocument();
  });

  it("shows the adopted identity once the panel connects, without leaving the page", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setViewport(1280);
    vi.stubGlobal(
      "open",
      vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
    );
    const created = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: null,
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { router } = renderRoute(`/p/${project.id}/accounts/${created.id}`);
    const details = (
      await screen.findByText("Connection & technical details")
    ).closest("details")!;
    await user.click(
      await within(details).findByRole("button", { name: "Connect" }),
    );

    // The backend adopts the identity on completion; health then says Ready.
    api.accountHealth.set(project.id, [
      health(created, {
        identity: {
          name: "Cyber Channel",
          username: "cyberchannel",
          avatar_url: null,
        },
      }),
    ]);
    const overviewCalls = () =>
      api.requests.filter((r) => r.path.startsWith("/overview")).length;
    const before = overviewCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
    });

    await vi.waitFor(() =>
      expect(cards()[0]).toHaveTextContent("YouTube @cyberchannel"),
    );
    expect(cards()[0]).toHaveTextContent("Ready");
    expect(
      screen.getByRole("complementary", { name: "YouTube @cyberchannel" }),
    ).toHaveTextContent("Connected as");
    expect(router.state.location.pathname).toBe(
      `/p/${project.id}/accounts/${created.id}`,
    );
    expect(overviewCalls()).toBeGreaterThan(before);
  });

  it("shows the detail beside the list on desktop and alone on phones", async () => {
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: "ok",
    });
    api.accountHealth.set(project.id, [health(account)]);

    setViewport(1280);
    renderRoute(`/p/${project.id}/accounts/${account.id}`);
    expect(
      await screen.findByRole("complementary", { name: "YouTube @ok" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Accounts" })).toBeVisible();
    cleanup();

    setViewport(375);
    renderRoute(`/p/${project.id}/accounts/${account.id}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: "YouTube @ok" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Accounts" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });
});
