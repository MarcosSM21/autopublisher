import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CHANNEL, FakeApi } from "../test-fake-api.ts";
import type { Account, Project, YouTubeChannel } from "../types.ts";
import AccountList from "./AccountList.tsx";
import YouTubeConnectionPanel, {
  POLL_INTERVAL_MS,
} from "./YouTubeConnectionPanel.tsx";

const OTHER_CHANNEL: YouTubeChannel = {
  id: "UC_OTHER_2",
  title: "Other Channel",
  handle: "@other",
  thumbnail_url: null,
};

let api: FakeApi;
let project: Project;
let account: Account;
let tab: { location: { href: string }; close: ReturnType<typeof vi.fn> };
let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "cyberchannel",
    display_name: "Cyber",
  });
  tab = { location: { href: "" }, close: vi.fn() };
  openSpy = vi.fn(() => tab);
  vi.stubGlobal("open", openSpy);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function setup() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

function renderPanel(
  selected: Account = account,
  projectActive: boolean = true,
) {
  return render(
    <YouTubeConnectionPanel account={selected} projectActive={projectActive} />,
  );
}

async function poll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });
}

function authorizeCalls() {
  return api.requests.filter((r) => r.path.endsWith("/authorize"));
}

describe("YouTubeConnectionPanel connect (US1)", () => {
  it("shows Not connected and connects through Google", async () => {
    const user = setup();
    renderPanel();

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(openSpy).toHaveBeenCalledWith("", "_blank");
    expect(tab.location.href).toMatch(
      /^https:\/\/accounts\.google\.com\/o\/oauth2\/v2\/auth/,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waiting for the authorization in Google",
    );

    await poll();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Cyber Channel")).toBeInTheDocument();
    expect(screen.getByText("Channel ID: UC_TEST_1")).toBeInTheDocument();
    expect(tab.close).not.toHaveBeenCalled();
  });

  it("only queries the connection of YouTube accounts", async () => {
    const instagram = api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "cyber",
    });
    render(
      <AccountList
        accounts={[account, instagram]}
        projectActive
        onUpdate={vi.fn()}
      />,
    );

    expect(
      await screen.findByRole("group", {
        name: "YouTube connection of @cyberchannel",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "YouTube connection of @cyber" }),
    ).not.toBeInTheDocument();
    const queried = api.requests
      .filter((r) => r.path.endsWith("/youtube-connection"))
      .map((r) => r.path);
    expect(queried).toEqual([`/accounts/${account.id}/youtube-connection`]);
  });

  it("shows a link when the browser blocks the new tab", async () => {
    openSpy.mockReturnValue(null);
    const user = setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Connect" }));

    expect(
      screen.getByRole("link", { name: "Open Google authorization" }),
    ).toHaveAttribute("href", expect.stringContaining("accounts.google.com"));
  });

  it("does not open any tab when OAuth is not configured", async () => {
    api.oauthConfigured = false;
    const user = setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Connect" }));

    expect(screen.getByRole("note")).toHaveTextContent(
      "YouTube OAuth is not configured",
    );
    expect(openSpy).not.toHaveBeenCalled();
    expect(authorizeCalls()).toHaveLength(0);
  });

  it("closes the opened tab when authorize fails", async () => {
    const user = setup();
    renderPanel();
    await screen.findByRole("button", { name: "Connect" });
    api.failNext(503, {
      error: {
        code: "oauth_not_configured",
        message: "YouTube integration is not configured.",
        fields: [],
      },
    });

    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(tab.close).toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "YouTube integration is not configured.",
    );
  });
});

describe("YouTubeConnectionPanel errors (US2)", () => {
  it("shows a cancelled authorization and keeps Connect available", async () => {
    api.nextAttemptOutcome = {
      status: "failed",
      code: "oauth_cancelled",
      message: "The connection was cancelled in Google.",
    };
    const user = setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Connect" }));
    await poll();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The connection was cancelled in Google.",
    );
    expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled();
  });

  it.each([{ status: "expired" as const }, { status: "not_found" as const }])(
    "treats $status as an expired authorization",
    async (outcome) => {
      api.nextAttemptOutcome = outcome;
      const user = setup();
      renderPanel();
      await user.click(await screen.findByRole("button", { name: "Connect" }));
      await poll();

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The authorization expired. Try again.",
      );
      const polls = api.requests.filter((r) =>
        r.path.startsWith("/youtube/oauth/attempts/"),
      ).length;
      await poll();
      expect(
        api.requests.filter((r) =>
          r.path.startsWith("/youtube/oauth/attempts/"),
        ).length,
      ).toBe(polls);
    },
  );

  it("shows the channel conflict message", async () => {
    api.nextAttemptOutcome = {
      status: "failed",
      code: "channel_already_connected",
      message:
        "This YouTube channel is already connected to @first in this project. Disconnect it there first.",
    };
    const user = setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Connect" }));
    await poll();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already connected to @first",
    );
  });
});

describe("YouTubeConnectionPanel disconnect (US3)", () => {
  it.each(["connected", "reconnect_required"] as const)(
    "disconnects a %s account after confirmation",
    async (status) => {
      api.setConnection(account.id, CHANNEL, status);
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const user = setup();
      renderPanel();

      await user.click(
        await screen.findByRole("button", { name: "Disconnect" }),
      );

      expect(await screen.findByText("Not connected")).toBeInTheDocument();
      const note = screen.getByText(/AutoPublisher deleted its stored/);
      expect(note).toHaveTextContent(
        "This affects every AutoPublisher connection",
      );
      expect(
        within(note).getByRole("link", {
          name: "myaccount.google.com/connections",
        }),
      ).toHaveAttribute("href", "https://myaccount.google.com/connections");
    },
  );

  it("does nothing when the confirmation is cancelled", async () => {
    api.setConnection(account.id);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path.endsWith("/disconnect"))).toBe(
      false,
    );
  });
});

describe("YouTubeConnectionPanel verify and reconnect (US4)", () => {
  it("shows Reconnect required with the linked channel", async () => {
    api.setConnection(account.id, CHANNEL, "reconnect_required");
    renderPanel();

    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
    expect(screen.getByText("Cyber Channel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Connect" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Verify connection" }),
    ).not.toBeInTheDocument();
  });

  it("applies the Connect protections to Reconnect from Reconnect required", async () => {
    api.setConnection(account.id, CHANNEL, "reconnect_required");
    api.oauthConfigured = false;
    const user = setup();
    const view = renderPanel();

    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    expect(screen.getByRole("note")).toHaveTextContent(
      "YouTube OAuth is not configured",
    );
    expect(openSpy).not.toHaveBeenCalled();
    expect(authorizeCalls()).toHaveLength(0);

    view.unmount();
    api.oauthConfigured = true;
    renderPanel();
    await screen.findByRole("button", { name: "Reconnect" });
    api.failNext(503, {
      error: {
        code: "oauth_not_configured",
        message: "Not configured.",
        fields: [],
      },
    });
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(tab.close).toHaveBeenCalled();
  });

  it("verifies a connected account", async () => {
    api.setConnection(account.id);
    const user = setup();
    renderPanel();

    await user.click(
      await screen.findByRole("button", { name: "Verify connection" }),
    );

    expect(await screen.findByText("Connection verified.")).toBeInTheDocument();
  });

  it("reloads the status when verification requires reconnecting", async () => {
    api.setConnection(account.id);
    const user = setup();
    renderPanel();
    await screen.findByRole("button", { name: "Verify connection" });
    api.failNext(409, {
      error: {
        code: "reconnect_required",
        message: "Google no longer accepts the stored credentials.",
        fields: [],
      },
    });
    api.setConnection(account.id, CHANNEL, "reconnect_required");

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Google no longer accepts the stored credentials.",
    );
    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
  });

  it("keeps Connected when YouTube is unreachable", async () => {
    api.setConnection(account.id);
    const user = setup();
    renderPanel();
    await screen.findByRole("button", { name: "Verify connection" });
    api.failNext(503, {
      error: {
        code: "youtube_unavailable",
        message: "Could not reach YouTube.",
        fields: [],
      },
    });

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach YouTube.",
    );
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});

describe("YouTubeConnectionPanel channel change (US5)", () => {
  async function reachWarning() {
    api.setConnection(account.id);
    api.nextAttemptOutcome = {
      status: "awaiting_confirmation",
      channel: OTHER_CHANNEL,
    };
    const user = setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    await poll();
    const warning = await screen.findByRole("region", {
      name: "Confirm channel change",
    });
    return { user, warning };
  }

  it("shows both channels and the account before replacing", async () => {
    const { warning } = await reachWarning();

    expect(warning).toHaveTextContent("YouTube @cyberchannel");
    expect(warning).toHaveTextContent("Current channel");
    expect(warning).toHaveTextContent("Channel ID: UC_TEST_1");
    expect(warning).toHaveTextContent("New channel");
    expect(warning).toHaveTextContent("Channel ID: UC_OTHER_2");
  });

  it("replaces the channel only after confirmation", async () => {
    const { user, warning } = await reachWarning();

    await user.click(
      within(warning).getByRole("button", {
        name: "Replace with this channel",
      }),
    );

    expect(await screen.findByText("Other Channel")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path.endsWith("/confirm"))).toBe(true);
  });

  it("keeps the current channel when cancelled", async () => {
    const { user, warning } = await reachWarning();

    await user.click(
      within(warning).getByRole("button", { name: "Keep current channel" }),
    );

    expect(
      screen.queryByRole("region", { name: "Confirm channel change" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Cyber Channel")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path.endsWith("/cancel"))).toBe(true);
  });

  it("applies the Connect protections to Reconnect from Connected", async () => {
    api.setConnection(account.id);
    api.oauthConfigured = false;
    const user = setup();
    const view = renderPanel();

    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    expect(openSpy).not.toHaveBeenCalled();
    expect(authorizeCalls()).toHaveLength(0);
    expect(screen.getByRole("note")).toBeInTheDocument();

    view.unmount();
    api.oauthConfigured = true;
    renderPanel();
    await screen.findByRole("button", { name: "Reconnect" });
    api.failNext(500, {
      error: { code: "internal_error", message: "Unexpected.", fields: [] },
    });
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(tab.close).toHaveBeenCalled();
  });
});

describe("YouTubeConnectionPanel inactive (US7)", () => {
  it.each([
    { label: "inactive account", accountActive: false, projectActive: true },
    { label: "inactive project", accountActive: true, projectActive: false },
  ])("keeps $label visible but not connectable", async (state) => {
    api.setConnection(account.id);
    const selected = { ...account, is_active: state.accountActive };
    renderPanel(selected, state.projectActive);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Cyber Channel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeDisabled();
    expect(
      screen.getByText("Reactivate the account (or project) to connect it."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
  });

  it("disables Connect for an inactive account", async () => {
    renderPanel({ ...account, is_active: false });

    expect(
      await screen.findByRole("button", { name: "Connect" }),
    ).toBeDisabled();
  });
});
