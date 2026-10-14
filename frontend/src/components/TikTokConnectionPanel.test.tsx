import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi, TT_IDENTITY } from "../test-fake-api.ts";
import type { Account, Project } from "../types.ts";
import AccountList from "./AccountList.tsx";
import TikTokConnectionPanel, {
  POLL_INTERVAL_MS,
} from "./TikTokConnectionPanel.tsx";

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
    platform: "tiktok",
    handle: "cyberstudio",
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
    <TikTokConnectionPanel account={selected} projectActive={projectActive} />,
  );
}

async function poll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
  });
}

function attemptPolls() {
  return api.requests.filter((r) =>
    r.path.startsWith("/tiktok/oauth/attempts/"),
  );
}

async function startConnecting() {
  const user = setup();
  renderPanel();
  await user.click(
    await screen.findByRole("button", { name: "Connect TikTok" }),
  );
  return user;
}

describe("TikTokConnectionPanel connect (US1)", () => {
  it("connects through TikTok and shows the connection", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const user = setup();
    api.nextTikTokOutcome = { status: "processing" };
    renderPanel();

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect TikTok" }));

    expect(openSpy).toHaveBeenCalledWith("", "_blank");
    expect(tab.location.href).toMatch(
      /^https:\/\/www\.tiktok\.com\/v2\/auth\/authorize\//,
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Connecting");
    expect(
      screen.getByRole("link", { name: "Reopen TikTok authorization" }),
    ).toHaveAttribute("href", tab.location.href);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();

    // Still processing: keeps polling every 2 s.
    await poll();
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    api.nextTikTokOutcome = { status: "completed", identity: TT_IDENTITY };
    await poll();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(attemptPolls()).toHaveLength(2);
    expect(screen.getByText("Cyber Studio")).toBeInTheDocument();
    expect(screen.getByText("@cyberstudio")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cyber Studio" })).toHaveAttribute(
      "src",
      TT_IDENTITY.avatar_url,
    );
    expect(screen.getByText(/^Access expires/)).toBeInTheDocument();
    expect(
      screen.getByText(/^Renewable authorization expires/),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Last verified/)).toBeInTheDocument();
    const permissions = screen.getByText(/^Permissions/);
    expect(permissions).toHaveTextContent("user.info.basic, video.publish");
    expect(permissions).toHaveTextContent(
      "according to TikTok's last authorization",
    );
    expect(document.body).not.toHaveTextContent(/verified now/i);
    expect(
      screen.queryByRole("link", { name: "Reopen TikTok authorization" }),
    ).not.toBeInTheDocument();
    expect(tab.close).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    expect(window.localStorage).toHaveLength(0);
    expect(window.sessionStorage).toHaveLength(0);
  });

  it("shows a neutral placeholder when the avatar is missing or fails", async () => {
    api.setTikTokConnection(account.id, { ...TT_IDENTITY, avatar_url: null });
    renderPanel();

    expect(
      await screen.findByTestId("tiktok-avatar-placeholder"),
    ).toBeInTheDocument();
    cleanup();

    api.setTikTokConnection(account.id);
    renderPanel();
    const image = await screen.findByRole("img", { name: "Cyber Studio" });
    act(() => {
      image.dispatchEvent(new Event("error"));
    });
    expect(screen.getByTestId("tiktok-avatar-placeholder")).toBeInTheDocument();
  });

  it("describes renewed permissions as coming from the last renewal", async () => {
    api.setTikTokConnection(account.id);
    api.tiktokConnections.get(account.id)!.permissions!.source =
      "token_refresh";
    renderPanel();

    expect(await screen.findByText(/^Permissions/)).toHaveTextContent(
      "according to TikTok's last renewal",
    );
  });

  it("shows setup guidance and no connect action when not configured", async () => {
    api.tiktokConfigured = false;
    renderPanel();

    expect(await screen.findByRole("note")).toHaveTextContent(
      "docs/tiktok-accounts.md",
    );
    expect(
      screen.queryByRole("button", { name: "Connect TikTok" }),
    ).not.toBeInTheDocument();
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("is rendered only for TikTok accounts", async () => {
    const threads = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "cyber",
    });
    render(
      <AccountList
        accounts={[account, threads]}
        projectActive
        onUpdate={vi.fn()}
      />,
    );

    expect(
      await screen.findByRole("group", {
        name: "TikTok connection of @cyberstudio",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "TikTok connection of @cyber" }),
    ).not.toBeInTheDocument();
    const queried = api.requests
      .filter((r) => r.path.endsWith("/tiktok-connection"))
      .map((r) => r.path);
    expect(queried).toEqual([`/accounts/${account.id}/tiktok-connection`]);
  });

  it("closes the tab and shows the error when authorize fails", async () => {
    api.tiktokConfigured = true;
    const user = setup();
    renderPanel();
    await screen.findByRole("button", { name: "Connect TikTok" });
    api.tiktokConfigured = false;

    await user.click(screen.getByRole("button", { name: "Connect TikTok" }));

    expect(tab.close).toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "TikTok integration is not configured",
    );
  });
});

describe("TikTokConnectionPanel errors (US2)", () => {
  it.each([
    ["tiktok_oauth_denied", "The connection was cancelled in TikTok."],
    [
      "tiktok_oauth_provider_error",
      "TikTok could not complete the authorization.",
    ],
    [
      "tiktok_oauth_callback_invalid",
      "The response from TikTok was not valid. Start the connection again.",
    ],
    [
      "tiktok_permission_missing",
      "TikTok did not grant every requested permission (missing: video.publish). Connect again and grant both permissions.",
    ],
    [
      "tiktok_token_exchange_failed",
      "TikTok did not complete the authorization. Start the connection again.",
    ],
    [
      "tiktok_unavailable",
      "Could not reach TikTok to finish the authorization.",
    ],
  ])("shows %s and allows a new attempt", async (code, message) => {
    api.nextTikTokOutcome = { status: "failed", code, message };
    const user = await startConnecting();

    await poll();

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    api.nextTikTokOutcome = { status: "completed", identity: TT_IDENTITY };
    await user.click(screen.getByRole("button", { name: "Connect TikTok" }));
    await poll();
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("names the missing permission", async () => {
    api.nextTikTokOutcome = {
      status: "failed",
      code: "tiktok_permission_missing",
      message:
        "TikTok did not grant every requested permission (missing: video.publish). Connect again and grant both permissions.",
    };
    await startConnecting();

    await poll();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("video.publish");
    expect(alert).toHaveTextContent("grant both permissions");
  });

  it.each([
    [{ status: "expired" } as const, "The authorization expired. Try again."],
    [{ status: "not_found" } as const, "The authorization expired. Try again."],
  ])("explains an expired attempt", async (outcome, message) => {
    api.nextTikTokOutcome = outcome;
    await startConnecting();

    await poll();

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(
      screen.getByRole("button", { name: "Connect TikTok" }),
    ).toBeEnabled();
  });

  it("keeps the previous connection after a failed attempt", async () => {
    api.setTikTokConnection(account.id);
    api.nextTikTokOutcome = {
      status: "failed",
      code: "tiktok_unavailable",
      message: "Could not reach TikTok to finish the authorization.",
    };
    renderPanel();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Cyber Studio")).toBeInTheDocument();
  });

  it("Cancel cancels the attempt and stops polling", async () => {
    const user = await startConnecting();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      api.requests.some(
        (r) => r.method === "POST" && r.path.endsWith("/cancel"),
      ),
    ).toBe(true);
    expect(
      await screen.findByText("The connection was cancelled."),
    ).toBeInTheDocument();
    const polls = attemptPolls().filter((r) => r.method === "GET").length;
    await poll();
    await poll();
    expect(attemptPolls().filter((r) => r.method === "GET")).toHaveLength(
      polls,
    );
    expect(
      screen.getByRole("button", { name: "Connect TikTok" }),
    ).toBeEnabled();
    expect(
      [...api.tiktokAttempts.values()].map((attempt) => attempt.status),
    ).toEqual(["cancelled"]);
  });

  it("shows a cancellation seen while polling", async () => {
    await startConnecting();
    for (const attempt of api.tiktokAttempts.values()) {
      attempt.status = "cancelled";
    }

    await poll();

    expect(
      await screen.findByText("The connection was cancelled."),
    ).toBeInTheDocument();
  });

  it("stops polling when unmounted", async () => {
    api.nextTikTokOutcome = { status: "processing" };
    const user = setup();
    const { unmount } = renderPanel();
    await user.click(
      await screen.findByRole("button", { name: "Connect TikTok" }),
    );

    unmount();
    await poll();
    await poll();

    expect(attemptPolls()).toHaveLength(0);
  });
});

function postsTo(suffix: string) {
  return api.requests.filter(
    (r) => r.method === "POST" && r.path.endsWith(suffix),
  );
}

async function renderConnected(status?: "connected" | "reconnect_required") {
  api.setTikTokConnection(account.id, TT_IDENTITY, status);
  const user = setup();
  renderPanel();
  await screen.findByText("Cyber Studio");
  return user;
}

describe("TikTokConnectionPanel verify and expiry (US3)", () => {
  it("Verify updates the last check without claiming a live publish check", async () => {
    const user = await renderConnected();

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Connection verified with TikTok",
    );
    expect(postsTo("/verify")).toHaveLength(1);
    expect(screen.getByText(/^Last verified/)).toHaveTextContent(
      "Last verified",
    );
    expect(screen.getByText(/^Permissions/)).toHaveTextContent(
      "according to TikTok's last authorization",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "last authorization or renewal",
    );
    expect(document.body).not.toHaveTextContent(/checked now|live/i);
  });

  it("shows a failed Verify and the reconnect-required state", async () => {
    api.tiktokVerifyError = {
      status: 409,
      code: "tiktok_identity_mismatch",
      message: "TikTok reports a different account than the linked one.",
    };
    const user = await renderConnected();

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "different account",
    );
    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
  });

  it("explains Reconnect required and offers Reconnect and Disconnect only", async () => {
    await renderConnected("reconnect_required");

    expect(screen.getByRole("note")).toHaveTextContent(
      "no longer accepts the saved authorization",
    );
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Verify connection" }),
    ).not.toBeInTheDocument();
  });
});

describe("TikTokConnectionPanel disconnect (US4)", () => {
  async function confirmDisconnect(user: ReturnType<typeof setup>) {
    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    const dialog = screen.getByRole("alertdialog", {
      name: "Disconnect TikTok",
    });
    expect(dialog).toHaveTextContent("revoke its access in TikTok");
    await user.click(
      screen.getByRole("button", { name: "Confirm disconnect" }),
    );
  }

  it("asks for confirmation and can keep the connection", async () => {
    const user = await renderConnected();

    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    await user.click(screen.getByRole("button", { name: "Keep connection" }));

    expect(postsTo("/disconnect")).toHaveLength(0);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it.each([
    ["revoked", "TikTok confirmed that AutoPublisher's access was revoked"],
    ["already_invalid", "no longer valid, so there was nothing left to revoke"],
  ] as const)("reports %s distinctly", async (revocation, text) => {
    api.nextTikTokDisconnect = revocation;
    const user = await renderConnected();

    await confirmDisconnect(user);

    expect(await screen.findByRole("status")).toHaveTextContent(text);
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    if (revocation === "already_invalid") {
      expect(screen.getByRole("status")).not.toHaveTextContent(
        "confirmed that",
      );
    }
  });

  it("offers Retry and local removal after a failed revocation", async () => {
    api.nextTikTokDisconnect = {
      status: 503,
      code: "tiktok_revoke_failed",
      message:
        "TikTok did not confirm the revocation, so the connection was kept.",
    };
    const user = await renderConnected();

    await confirmDisconnect(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "did not confirm the revocation",
    );
    expect(screen.getByText("Connected")).toBeInTheDocument();
    api.nextTikTokDisconnect = "revoked";
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "access was revoked",
    );
    expect(postsTo("/disconnect")).toHaveLength(2);
  });

  it("removes locally after a missing credential, with a second confirmation", async () => {
    api.nextTikTokDisconnect = {
      status: 409,
      code: "tiktok_credential_missing",
      message:
        "The stored TikTok credentials are missing. TikTok may still have AutoPublisher authorized.",
    };
    const user = await renderConnected();
    await confirmDisconnect(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "may still have AutoPublisher authorized",
    );
    expect(
      screen.queryByRole("button", { name: "Retry" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove locally without revoking" }),
    );
    const dialog = screen.getByRole("alertdialog", {
      name: "Remove locally without revoking",
    });
    expect(dialog).toHaveTextContent("Manage app permissions");
    expect(postsTo("/remove-local")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Remove locally" }));

    expect(postsTo("/remove-local")).toHaveLength(1);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Removed locally without revoking",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Manage app permissions",
    );
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("can go back from the local removal", async () => {
    api.nextTikTokDisconnect = {
      status: 503,
      code: "tiktok_revoke_failed",
      message: "TikTok did not confirm the revocation.",
    };
    const user = await renderConnected();
    await confirmDisconnect(user);
    await user.click(
      await screen.findByRole("button", {
        name: "Remove locally without revoking",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(postsTo("/remove-local")).toHaveLength(0);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});

describe("TikTokConnectionPanel reconnect (US5)", () => {
  it.each(["connected", "reconnect_required"] as const)(
    "reconnects from %s",
    async (status) => {
      const user = await renderConnected(status);

      await user.click(screen.getByRole("button", { name: "Reconnect" }));
      await poll();

      expect(openSpy).toHaveBeenCalledTimes(1);
      expect(postsTo("/authorize")).toHaveLength(1);
      expect(await screen.findByRole("status")).toHaveTextContent(
        "TikTok account connected.",
      );
      expect(screen.getByText("Connected")).toBeInTheDocument();
    },
  );

  const other = {
    open_id: "-000fake-tt-other-open-id-b52e90",
    display_name: "Other Studio",
    avatar_url: null,
  };

  async function awaitingChange() {
    api.nextTikTokOutcome = {
      status: "awaiting_confirmation",
      identity: other,
    };
    const user = await renderConnected();
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    await poll();
    const dialog = await screen.findByRole("alertdialog", {
      name: "Replace the TikTok account",
    });
    expect(dialog).toHaveTextContent("Cyber Studio (ID ending in 7d1c3e)");
    expect(dialog).toHaveTextContent("Other Studio (ID ending in b52e90)");
    return user;
  }

  it("Replace confirms the account change", async () => {
    const user = await awaitingChange();

    await user.click(screen.getByRole("button", { name: "Replace" }));

    expect(postsTo("/confirm")).toHaveLength(1);
    expect(await screen.findByText("Other Studio")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "TikTok account replaced.",
    );
  });

  it("Cancel keeps the linked account", async () => {
    const user = await awaitingChange();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(postsTo("/cancel")).toHaveLength(1);
    expect(postsTo("/confirm")).toHaveLength(0);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "linked TikTok account is unchanged",
    );
    expect(screen.getByText("Cyber Studio")).toBeInTheDocument();
  });
});

describe("TikTokConnectionPanel inactive entities (US7)", () => {
  it.each([
    ["account", false, true],
    ["project", true, false],
  ] as const)(
    "an inactive %s keeps status and Disconnect only",
    async (_entity, accountActive, projectActive) => {
      api.setTikTokConnection(account.id);
      const selected = { ...account, is_active: accountActive };
      renderPanel(selected, projectActive);

      expect(await screen.findByText("Connected")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
      for (const name of ["Connect TikTok", "Reconnect", "Verify connection"]) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
      }
      expect(screen.getByText(/^Reactivate the account/)).toBeInTheDocument();
    },
  );

  it("an inactive account without connection offers no Connect", async () => {
    renderPanel({ ...account, is_active: false });

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Connect TikTok" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Disconnect" }),
    ).not.toBeInTheDocument();
  });
});
