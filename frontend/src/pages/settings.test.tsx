import { cleanup, screen, within } from "@testing-library/react";
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
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/platforms" && !failed) {
        failed = true;
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

    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(
      "Loading platform integrations…",
    );
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Couldn't load the platform integrations");
    within(error).getByRole("button", { name: "Retry" }).click();
    expect(
      await screen.findByRole("list", { name: "Platform integrations" }),
    ).toBeInTheDocument();
  });

  it("shows the pause on Posts only in the project strip, without a control", async () => {
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
    expect(
      screen.queryByRole("region", { name: "Automatic publishing is paused" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /Pause automation|Resume automation/,
      }),
    ).not.toBeInTheDocument();
  });
});
