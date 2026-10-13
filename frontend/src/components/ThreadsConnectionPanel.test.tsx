import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi, TH_IDENTITY, TH_REDIRECT_URI } from "../test-fake-api.ts";
import type { Account, Project, ThreadsIdentity } from "../types.ts";
import AccountList from "./AccountList.tsx";
import ThreadsConnectionPanel from "./ThreadsConnectionPanel.tsx";

const PASTED = `${TH_REDIRECT_URI}?code=secret-code-1&state=secret-state-1#_`;

const OTHER_IDENTITY: ThreadsIdentity = {
  threads_user_id: "25840000000000002",
  username: "new.account",
  display_name: null,
  profile_picture_url: null,
};

let api: FakeApi;
let project: Project;
let account: Account;
let tab: { location: { href: string }; close: ReturnType<typeof vi.fn> };
let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  account = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "cyberstudio",
    display_name: "Cyber",
  });
  tab = { location: { href: "" }, close: vi.fn() };
  openSpy = vi.fn(() => tab);
  vi.stubGlobal("open", openSpy);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPanel(
  selected: Account = account,
  projectActive: boolean = true,
) {
  return render(
    <ThreadsConnectionPanel account={selected} projectActive={projectActive} />,
  );
}

function pasteField() {
  return screen.getByLabelText(
    "Paste the address of the page Threads opened",
  ) as HTMLInputElement;
}

async function startConnect(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: "Connect Threads" }),
  );
  return pasteField();
}

async function pasteAndComplete(
  user: ReturnType<typeof userEvent.setup>,
  value: string = PASTED,
) {
  // Pasting sets the whole value at once, like a real paste.
  fireEvent.change(pasteField(), { target: { value } });
  await user.click(screen.getByRole("button", { name: "Complete connection" }));
}

function completeRequests() {
  return api.requests.filter((r) => r.path.endsWith("/complete"));
}

describe("ThreadsConnectionPanel connect (US1)", () => {
  it("connects through the pasted redirect address", async () => {
    const user = userEvent.setup();
    api.nextThreadsOutcome = {
      status: "completed",
      identity: {
        ...TH_IDENTITY,
        profile_picture_url: "https://scontent.example/th-pic.jpg",
      },
    };
    renderPanel();

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    const field = await startConnect(user);

    expect(openSpy).toHaveBeenCalledWith("", "_blank");
    expect(tab.location.href).toMatch(
      /^https:\/\/threads\.com\/oauth\/authorize/,
    );
    expect(field).toHaveValue("");

    await pasteAndComplete(user);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    const [request] = completeRequests();
    expect(request.body).toEqual({ redirect_url: PASTED });
    expect(request.path).not.toContain("secret");
    expect(screen.getByText("@cyber.studio")).toBeInTheDocument();
    expect(screen.getByText("Cyber Studio")).toBeInTheDocument();
    expect(
      screen.getByText("Threads user ID: 25841234567890123"),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Access expires/)).toBeInTheDocument();
    expect(screen.getByText(/^Data access expires/)).toBeInTheDocument();
    expect(screen.getByText(/^Last verified/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "@cyber.studio" })).toHaveAttribute(
      "src",
      "https://scontent.example/th-pic.jpg",
    );
    expect(
      screen.queryByLabelText("Paste the address of the page Threads opened"),
    ).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("secret-code-1");
    expect(document.body.innerHTML).not.toContain("secret-state-1");
  });

  it("shows a placeholder when the picture fails and hides a missing name", async () => {
    api.setThreadsConnection(account.id, {
      ...OTHER_IDENTITY,
      profile_picture_url: "https://scontent.example/broken.jpg",
    });
    renderPanel();

    const picture = await screen.findByRole("img", { name: "@new.account" });
    fireEvent.error(picture);

    expect(
      screen.queryByRole("img", { name: "@new.account" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("@new.account")).toBeInTheDocument();
    expect(screen.queryByText("Cyber Studio")).not.toBeInTheDocument();
  });

  it("shows a link when the browser blocks the new tab", async () => {
    const user = userEvent.setup();
    openSpy.mockReturnValue(null);
    renderPanel();

    await startConnect(user);

    expect(
      screen.getByRole("link", { name: "Open Threads authorization" }),
    ).toHaveAttribute(
      "href",
      expect.stringMatching(/^https:\/\/threads\.com\/oauth\/authorize/),
    );
  });

  it("shows setup guidance and no connect action when not configured", async () => {
    api.threadsConfigured = false;
    renderPanel();

    expect(await screen.findByRole("note")).toHaveTextContent(
      "Threads is not configured",
    );
    expect(
      screen.queryByRole("button", { name: "Connect Threads" }),
    ).not.toBeInTheDocument();
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("is only rendered for Threads accounts", async () => {
    const instagram = api.addAccount({
      project_id: project.id,
      platform: "instagram",
      handle: "cyberinsta",
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
        name: "Threads connection of @cyberstudio",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("group", {
        name: "Threads connection of @cyberinsta",
      }),
    ).not.toBeInTheDocument();
    const queried = api.requests
      .filter((r) => r.path.endsWith("/threads-connection"))
      .map((r) => r.path);
    expect(queried).toEqual([`/accounts/${account.id}/threads-connection`]);
  });

  it("cancels a pending attempt", async () => {
    const user = userEvent.setup();
    renderPanel();
    await startConnect(user);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      screen.queryByLabelText("Paste the address of the page Threads opened"),
    ).not.toBeInTheDocument();
    expect(api.requests.at(-1)?.path).toMatch(/\/cancel$/);
    expect(
      screen.getByRole("button", { name: "Connect Threads" }),
    ).toBeEnabled();
  });
});

describe("ThreadsConnectionPanel errors (US2)", () => {
  it.each([
    [400, "threads_oauth_denied", "The connection was cancelled in Threads."],
    [
      400,
      "threads_oauth_provider_error",
      "Threads could not complete the authorization.",
    ],
    [
      410,
      "threads_oauth_attempt_expired",
      "This authorization has expired. Start the connection again.",
    ],
    [
      422,
      "threads_permission_missing",
      "Grant all requested permissions to connect the account. Missing: threads_content_publish.",
    ],
  ])("shows %s %s and allows a new attempt", async (status, code, message) => {
    const user = userEvent.setup();
    renderPanel();
    await startConnect(user);
    api.failNext(status, { error: { code, message, fields: [] } });

    await pasteAndComplete(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Paste the address of the page Threads opened"),
    ).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("secret-code-1");
    expect(
      screen.getByRole("button", { name: "Connect Threads" }),
    ).toBeEnabled();
  });

  it("keeps the paste field after an invalid state so the user can paste again", async () => {
    const user = userEvent.setup();
    renderPanel();
    await startConnect(user);
    api.failNext(400, {
      error: {
        code: "threads_oauth_state_invalid",
        message:
          "The pasted address does not belong to this connection attempt.",
        fields: [],
      },
    });

    await pasteAndComplete(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not belong to this connection attempt",
    );
    expect(pasteField()).toHaveValue("");
    expect(document.body.innerHTML).not.toContain("secret-code-1");

    await pasteAndComplete(user);
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it.each([
    "https://localhost.evil.example/autopublisher/threads/callback?code=x&state=y",
    "https://localhost:8443/autopublisher/threads/callback?code=x&state=y",
  ])("rejects %s and keeps the field for a correct paste", async (address) => {
    const user = userEvent.setup();
    renderPanel();
    await startConnect(user);

    await pasteAndComplete(user, address);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "not the address Threads redirected to",
    );
    expect(pasteField()).toHaveValue("");

    await pasteAndComplete(user);
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });
});

describe("ThreadsConnectionPanel disconnect (US3)", () => {
  it("disconnects after confirming and explains manual revocation", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Threads → Settings → Account → Website permissions",
    );
  });

  it("does nothing when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(api.requests.some((r) => r.path.endsWith("/disconnect"))).toBe(
      false,
    );
  });

  it("keeps the error visible when the secure storage is unavailable", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    api.failNext(503, {
      error: {
        code: "credential_store_unavailable",
        message: "The system's secure credential storage is not available.",
        fields: [],
      },
    });
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "secure credential storage is not available",
    );
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});

describe("ThreadsConnectionPanel verify (US4)", () => {
  it("verifies and shows the updated identity", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();
    await screen.findByText("@cyber.studio");
    api.setThreadsConnection(account.id, {
      ...TH_IDENTITY,
      username: "renamed.studio",
    });

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByText("@renamed.studio")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Connection verified.",
    );
  });

  it("shows Reconnect required with Reconnect and Disconnect but no Verify", async () => {
    api.setThreadsConnection(account.id, TH_IDENTITY, "reconnect_required");
    renderPanel();

    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(
      "Reconnect the account to renew it",
    );
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Verify connection" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("@cyber.studio")).toBeInTheDocument();
  });

  it.each([
    [
      409,
      "threads_reconnect_required",
      "A required Threads permission is missing or was withdrawn (threads_content_publish). Reconnect the account and grant all requested permissions.",
    ],
    [
      409,
      "threads_identity_mismatch",
      "The authorized Threads account no longer matches the linked account. Reconnect the account to change it.",
    ],
  ])("shows %s %s and reloads the state", async (status, code, message) => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();
    await screen.findByText("Connected");
    api.failNext(status, { error: { code, message, fields: [] } });
    api.setThreadsConnection(account.id, TH_IDENTITY, "reconnect_required");

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
  });

  it("keeps Connected when Threads is unreachable", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();
    await screen.findByText("Connected");
    api.failNext(503, {
      error: {
        code: "threads_unavailable",
        message:
          "Could not reach Threads. Check your connection and try again.",
        fields: [],
      },
    });

    await user.click(screen.getByRole("button", { name: "Verify connection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach Threads",
    );
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});

describe("ThreadsConnectionPanel account change (US5)", () => {
  async function reconnectToOther(user: ReturnType<typeof userEvent.setup>) {
    api.nextThreadsOutcome = {
      status: "awaiting_confirmation",
      identity: OTHER_IDENTITY,
    };
    await user.click(await screen.findByRole("button", { name: "Reconnect" }));
    await pasteAndComplete(user);
    return screen.findByRole("region", {
      name: "Confirm Threads account change",
    });
  }

  it.each(["connected", "reconnect_required"] as const)(
    "reconnects the same account from %s",
    async (status) => {
      const user = userEvent.setup();
      api.setThreadsConnection(account.id, TH_IDENTITY, status);
      renderPanel();

      await user.click(
        await screen.findByRole("button", { name: "Reconnect" }),
      );
      await pasteAndComplete(user);

      expect(await screen.findByText("Connected")).toBeInTheDocument();
      expect(
        screen.getByText("Threads account connected."),
      ).toBeInTheDocument();
    },
  );

  it("shows both accounts and the affected AutoPublisher account", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();

    const region = await reconnectToOther(user);

    expect(region).toHaveTextContent("Threads @cyberstudio (Cyber)");
    expect(within(region).getByText("@cyber.studio")).toBeInTheDocument();
    expect(
      within(region).getByText("Threads user ID: 25841234567890123"),
    ).toBeInTheDocument();
    expect(within(region).getByText("@new.account")).toBeInTheDocument();
    expect(
      within(region).getByText("Threads user ID: 25840000000000002"),
    ).toBeInTheDocument();
  });

  it("replaces the account only after confirmation", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();
    await reconnectToOther(user);
    expect(api.threadsConnections.get(account.id)?.identity).toEqual(
      TH_IDENTITY,
    );

    await user.click(
      screen.getByRole("button", { name: "Replace with the new account" }),
    );

    expect(await screen.findByText("@new.account")).toBeInTheDocument();
    expect(api.requests.at(-1)?.path).toMatch(/\/confirm$/);
    expect(
      screen.queryByRole("region", { name: "Confirm Threads account change" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the current account when cancelled", async () => {
    const user = userEvent.setup();
    api.setThreadsConnection(account.id);
    renderPanel();
    await reconnectToOther(user);

    await user.click(
      screen.getByRole("button", { name: "Keep current account" }),
    );

    expect(api.requests.at(-1)?.path).toMatch(/\/cancel$/);
    expect(
      screen.queryByRole("region", { name: "Confirm Threads account change" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("@cyber.studio")).toBeInTheDocument();
    expect(api.threadsConnections.get(account.id)?.identity).toEqual(
      TH_IDENTITY,
    );
  });
});

describe("ThreadsConnectionPanel inactive (US7)", () => {
  it("disables Connect for an inactive account", async () => {
    const inactive = { ...account, is_active: false };
    renderPanel(inactive);

    expect(
      await screen.findByRole("button", { name: "Connect Threads" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Reactivate the account \(or project\)/),
    ).toBeInTheDocument();
  });

  it.each([
    ["an inactive account", false, true],
    ["an inactive project", true, false],
  ])(
    "blocks Reconnect and Verify but allows Disconnect for %s",
    async (_label, accountActive, projectActive) => {
      api.setThreadsConnection(account.id);
      renderPanel({ ...account, is_active: accountActive }, projectActive);

      expect(
        await screen.findByRole("button", { name: "Reconnect" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Verify connection" }),
      ).toBeDisabled();
      expect(screen.getByRole("button", { name: "Disconnect" })).toBeEnabled();
      expect(
        screen.getByText(/Reactivate the account \(or project\)/),
      ).toBeInTheDocument();
    },
  );
});
