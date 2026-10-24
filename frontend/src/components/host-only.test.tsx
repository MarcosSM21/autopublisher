// YouTube and TikTok OAuth are host-only (Feature 020 T025, contracts/ui.md §4).
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Project } from "../types.ts";
import InstagramConnectionPanel from "./InstagramConnectionPanel.tsx";
import TikTokConnectionPanel from "./TikTokConnectionPanel.tsx";
import YouTubeConnectionPanel from "./YouTubeConnectionPanel.tsx";

/** Vitest's jsdom environment exposes its JSDOM instance as `jsdom`. */
const dom = (
  globalThis as unknown as { jsdom: { reconfigure(o: { url: string }): void } }
).jsdom;

const LAN_PAGE = "http://192.168.1.40:8000/p/1/accounts/2?tab=connection";
const HOST_ONLY = {
  error: {
    code: "host_only_action",
    message:
      "Connect this account from the computer that runs AutoPublisher, at http://127.0.0.1:8000.",
    fields: [],
  },
};

let api: FakeApi;
let project: Project;
let original: string;

beforeEach(() => {
  original = window.location.href;
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  vi.stubGlobal(
    "open",
    vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
  );
});

afterEach(() => {
  cleanup();
  dom.reconfigure({ url: original });
  vi.unstubAllGlobals();
});

function account(platform: Account["platform"]): Account {
  return api.addAccount({
    project_id: project.id,
    platform,
    handle: `cyber-${platform}`,
    display_name: "Cyber",
  });
}

function authorizeCalls() {
  return api.requests.filter((r) => r.path.endsWith("/authorize"));
}

const PANELS = [
  {
    platform: "youtube" as const,
    label: "YouTube",
    connect: "Connect",
    render: (selected: Account) =>
      render(<YouTubeConnectionPanel account={selected} projectActive />),
  },
  {
    platform: "tiktok" as const,
    label: "TikTok",
    connect: "Connect TikTok",
    render: (selected: Account) =>
      render(<TikTokConnectionPanel account={selected} projectActive />),
  },
];

describe.each(PANELS)(
  "$label connection",
  ({ platform, label, connect, render }) => {
    it("opened from another device, explains instead of starting a doomed flow", async () => {
      dom.reconfigure({ url: LAN_PAGE });
      render(account(platform));

      const note = await screen.findByRole("note");
      expect(note).toHaveTextContent(
        `Connect or reconnect ${label} from the computer that runs AutoPublisher.`,
      );
      expect(note).toHaveTextContent(
        "On that computer, open http://127.0.0.1:8000/p/1/accounts/2?tab=connection",
      );
      expect(screen.queryByRole("button", { name: connect })).toBeNull();
      expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
      expect(authorizeCalls()).toHaveLength(0);
    });

    it("on the host (loopback), keeps the Connect button", async () => {
      render(account(platform));
      expect(
        await screen.findByRole("button", { name: connect }),
      ).toBeInTheDocument();
      expect(screen.queryByText(/from the computer that runs/)).toBeNull();
    });

    it("a 409 host_only_action becomes the same explanation, not an error", async () => {
      const user = userEvent.setup();
      const selected = account(platform);
      api.failRequest(
        "POST",
        `/accounts/${selected.id}/${platform}-connection/authorize`,
        409,
        HOST_ONLY,
      );
      render(selected);

      await user.click(await screen.findByRole("button", { name: connect }));

      expect(
        await screen.findByText(
          `Connect or reconnect ${label} from the computer that runs AutoPublisher.`,
        ),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(HOST_ONLY.error.message)).toBeNull();
      expect(screen.queryByRole("button", { name: connect })).toBeNull();
    });
  },
);

it("a connected YouTube account can still be verified and disconnected remotely", async () => {
  dom.reconfigure({ url: LAN_PAGE });
  const selected = account("youtube");
  api.setConnection(selected.id);
  render(<YouTubeConnectionPanel account={selected} projectActive />);

  expect(
    await screen.findByRole("button", { name: "Verify connection" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Disconnect" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
});

it("Instagram is unchanged from another device", async () => {
  dom.reconfigure({ url: LAN_PAGE });
  render(
    <InstagramConnectionPanel account={account("instagram")} projectActive />,
  );

  expect(
    await screen.findByRole("button", { name: "Connect Instagram" }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/from the computer that runs/)).toBeNull();
});
