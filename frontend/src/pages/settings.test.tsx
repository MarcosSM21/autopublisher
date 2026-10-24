import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import { renderRoute } from "../test-utils.tsx";
import type { PlatformAvailability } from "../types.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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
    status: "partial",
    can_connect: true,
    missing: ["media_delivery"],
    message:
      "Media delivery is not configured: Instagram posts can't be published yet.",
  },
  {
    platform: "tiktok",
    label: "TikTok",
    integration_available: true,
    status: "not_configured",
    can_connect: false,
    missing: ["app_credentials"],
    message: "The TikTok app credentials are missing or invalid.",
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

describe("Settings", () => {
  it("mounts the automation status with its Pause/Resume control", async () => {
    renderRoute("/settings");

    const automation = await screen.findByRole("region", {
      name: "Automation",
    });
    expect(
      await within(automation).findByText("Automatic publishing is running."),
    ).toBeInTheDocument();
    expect(
      within(automation).getByRole("button", { name: "Pause automation" }),
    ).toBeInTheDocument();
  });

  it("lists each integration's state and only its sanitised message", async () => {
    api.platforms = PLATFORMS;
    renderRoute("/settings");

    const list = await screen.findByRole("list", {
      name: "Platform integrations",
    });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "YouTubeConfigured",
      "InstagramPartially configuredMedia delivery is not configured: Instagram posts can't be published yet.",
      "TikTokNot configuredThe TikTok app credentials are missing or invalid.",
      "XComing soon",
    ]);
    // Read-only: no actions, and nothing technical (internal ids, paths).
    expect(within(list).queryByRole("button")).not.toBeInTheDocument();
    expect(within(list).queryByRole("link")).not.toBeInTheDocument();
    expect(list.textContent).not.toMatch(
      /app_credentials|media_delivery|not_configured|coming_soon|\//,
    );
  });

  it("shows a skeleton while loading, then Retry after an error", async () => {
    api.platforms = PLATFORMS;
    const fetchMock = vi.mocked(fetch);
    const original = fetchMock.getMockImplementation()!;
    let failed = false;
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/platforms" && !failed) {
        failed = true;
        await held;
        return new Response(
          JSON.stringify({
            error: { code: "internal", message: "Something failed." },
          }),
          { status: 500 },
        );
      }
      return original(input, init);
    });
    renderRoute("/settings");

    // After the session bootstrap, the integrations load on their own.
    expect(
      await screen.findByText("Loading platform integrations…"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
    release();
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Couldn't load the platform integrations");
    within(error).getByRole("button", { name: "Retry" }).click();
    expect(
      await screen.findByRole("list", { name: "Platform integrations" }),
    ).toBeInTheDocument();
  });

  it("shows the pause on Posts in the strip and one banner (019 FR-058), without a control", async () => {
    const project = api.addProject({ name: "Cyber" });
    const overview = api.emptyOverview([project]);
    overview.automation = {
      paused: true,
      running: true,
      paused_automatic_posts: 2,
    };
    api.projectOverviews.set(project.id, overview);
    renderRoute(`/p/${project.id}/posts`);

    const strip = await screen.findByRole("navigation", {
      name: "Project status",
    });
    expect(
      within(strip).getByRole("link", {
        name: "Automation paused · 2 waiting",
      }),
    ).toHaveAttribute("href", "/settings");
    await screen.findByRole("heading", { level: 1, name: "Posts" });
    // One project banner explains the pause and leads to Settings.
    const banners = screen.getAllByRole("region", {
      name: "Automatic publishing is paused",
    });
    expect(banners).toHaveLength(1);
    expect(
      within(banners[0]).getByRole("link", { name: /Settings/ }),
    ).toHaveAttribute("href", "/settings");
    expect(
      screen.queryByRole("button", {
        name: /Pause automation|Resume automation/,
      }),
    ).not.toBeInTheDocument();
  });
});

// --- Feature 020: this installation and sign-in (T024) ----------------------

function installationSection() {
  return screen.findByRole("region", { name: "This installation" });
}

describe("Settings in the installed app", () => {
  beforeEach(() => {
    api.useInstallation({ authenticated: true });
  });

  it("development shows neither the installation nor the sign-in", async () => {
    api = new FakeApi();
    renderRoute("/settings", { api });

    await screen.findByRole("region", { name: "Automatic publishing" });
    expect(
      screen.queryByRole("region", { name: "This installation" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
    expect(api.requests.some((r) => r.path === "/system/status")).toBe(false);
  });

  it("a healthy installation with LAN off", async () => {
    renderRoute("/settings", { api });

    const section = await installationSection();
    expect(
      await within(section).findByText(/Everything is working/),
    ).toBeInTheDocument();
    expect(section).toHaveTextContent(
      "Only this computer can open AutoPublisher.",
    );
    expect(section).toHaveTextContent("Port 8000");
    expect(section).toHaveTextContent("restart the service");
    expect(within(section).queryByRole("note")).toBeNull();
    expect(section).not.toHaveTextContent(/encrypted\b(?! \(HTTP\))/);
  });

  it("LAN on lists the addresses, suggests names and always warns about HTTP", async () => {
    api.systemStatus.deployment = {
      port: 8000,
      lan_enabled: true,
      addresses: ["http://192.168.1.40:8000"],
      suggested_names: ["http://my-pc.local:8000"],
      allowed_hosts: ["my-pc.local"],
    };
    renderRoute("/settings", { api });

    const section = await installationSection();
    const addresses = await within(section).findByRole("list", {
      name: "Addresses",
    });
    expect(addresses).toHaveTextContent("http://192.168.1.40:8000");
    expect(section).toHaveTextContent(
      "This name may work on your network: http://my-pc.local:8000",
    );
    const warning = within(section).getByRole("note");
    expect(warning).toHaveTextContent(
      "Access over your network is not encrypted (HTTP).",
    );
    expect(warning).toHaveTextContent("private home network");
    expect(section).not.toHaveTextContent(/secure connection|is encrypted/i);
  });

  it("LAN on without a detected address says so neutrally", async () => {
    api.systemStatus.deployment = {
      port: 8000,
      lan_enabled: true,
      addresses: [],
      suggested_names: [],
      allowed_hosts: [],
    };
    renderRoute("/settings", { api });

    const section = await installationSection();
    expect(
      await within(section).findByText(/Could not detect this computer/),
    ).toBeInTheDocument();
    expect(within(section).getByRole("note")).toHaveTextContent("HTTP");
  });

  it.each([
    [
      "locked",
      "Secure storage is locked. Unlock your keyring on this computer",
    ],
    ["unavailable", "Secure storage is not available."],
    ["unknown", "Secure storage could not be checked"],
  ] as const)(
    "the credential store %s is a problem, never 'working'",
    async (status, text) => {
      api.systemStatus.credential_store = { status };
      renderRoute("/settings", { api });

      const section = await installationSection();
      const problems = await within(section).findByRole("list", {
        name: "Problems",
      });
      expect(problems).toHaveTextContent(text);
      expect(section).not.toHaveTextContent("Everything is working");
    },
  );

  it("reports a database that does not respond", async () => {
    api.systemStatus.database = { status: "error" };
    renderRoute("/settings", { api });

    const section = await installationSection();
    expect(
      await within(section).findByText(/The database is not responding/),
    ).toBeInTheDocument();
  });

  it("keeps the scheduler, pause and last check in Automatic publishing", async () => {
    api.automation = { ...api.automation, running: false };
    renderRoute("/settings", { api });

    const automation = await screen.findByRole("region", {
      name: "Automatic publishing",
    });
    expect(
      await within(automation).findByText("Automatic publishing is running."),
    ).toBeInTheDocument();
    expect(automation).toHaveTextContent("Last check");
    expect(automation).toHaveTextContent("Scheduler not running");
    expect(
      within(automation).getByRole("button", { name: "Pause automation" }),
    ).toBeInTheDocument();
  });
});

describe("Sign-in actions", () => {
  beforeEach(() => {
    api.useInstallation({ authenticated: true });
  });

  async function openChangePassword() {
    const user = userEvent.setup();
    renderRoute("/settings", { api });
    await user.click(
      await screen.findByRole("button", { name: "Change password" }),
    );
    const form = await screen.findByRole("form", { name: "Change password" });
    return { user, form };
  }

  async function fill(
    user: ReturnType<typeof userEvent.setup>,
    current: string,
    next: string,
    confirm = next,
  ) {
    if (current) {
      await user.type(screen.getByLabelText("Current password"), current);
    }
    await user.type(screen.getByLabelText(/^New password/), next);
    await user.type(screen.getByLabelText("Confirm new password"), confirm);
    await user.click(
      within(screen.getByRole("form", { name: "Change password" })).getByRole(
        "button",
        { name: "Change password" },
      ),
    );
  }

  function passwordChanges() {
    return api.requests.filter((r) => r.path === "/auth/password");
  }

  it("Sign out ends the session and goes to /login", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/settings", { api });

    await user.click(await screen.findByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(api.authSession.authenticated).toBe(false);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });

  it("Sign out with an already expired session still lands on /login", async () => {
    const user = userEvent.setup();
    const { router } = renderRoute("/settings", { api });
    const button = await screen.findByRole("button", { name: "Sign out" });
    api.expireSession();

    await user.click(button);

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("changes the password and keeps this browser signed in", async () => {
    const { user } = await openChangePassword();

    await fill(user, api.password, "a brand new passphrase");

    expect(
      await screen.findByText(
        "Password changed. Other devices have been signed out.",
      ),
    ).toBeInTheDocument();
    expect(api.password).toBe("a brand new passphrase");
    expect(screen.queryByRole("form", { name: "Change password" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });

  it("checks the confirmation and length before asking the server", async () => {
    const { user } = await openChangePassword();

    await fill(user, api.password, "a brand new passphrase", "something else");
    expect(
      await screen.findByText("The new passwords do not match."),
    ).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/^New password/));
    await user.clear(screen.getByLabelText("Confirm new password"));
    await fill(user, "", "short");
    expect(
      await screen.findByText("Use 12 to 1024 characters."),
    ).toBeInTheDocument();
    expect(passwordChanges()).toHaveLength(0);
  });

  it("explains a wrong current password", async () => {
    const { user } = await openChangePassword();

    await fill(user, "not the password", "a brand new passphrase");

    expect(
      await screen.findByText("Current password is incorrect."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(api.password).not.toBe("a brand new passphrase");
  });

  it("explains the rate limit", async () => {
    api.failRequest("POST", "/auth/password", 429, {
      error: {
        code: "too_many_attempts",
        message: "Too many attempts. Try again in a few minutes.",
        fields: [],
      },
    });
    const { user } = await openChangePassword();

    await fill(user, api.password, "a brand new passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Try again in a few minutes.",
    );
  });

  it("closing the dialog discards the typed passwords", async () => {
    const { user } = await openChangePassword();
    await user.type(screen.getByLabelText("Current password"), "typed secret");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByLabelText("Current password")).toHaveValue("");
  });
});
