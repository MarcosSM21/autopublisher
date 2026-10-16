import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import AssetUsage from "./AssetUsage.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("lists every publication of the asset", async () => {
  const project = api.addProject({ name: "L4i4" });
  const content = api.addContent({
    project_id: project.id,
    usage: {
      used: true,
      publication_count: 2,
      published_count: 0,
      awaiting_count: 1,
      scheduled_count: 0,
      platforms: ["tiktok"],
      last_published_at: null,
    },
  });
  const base = {
    account_id: 1,
    scheduled_at: null,
    published_at: null,
    created_at: "2026-10-05T10:00:00Z",
    updated_at: "2026-10-05T10:00:00Z",
    external_url: null,
  };
  api.usageHistory[content.id] = [
    {
      ...base,
      publication_id: 1,
      platform: "tiktok",
      account_name: "Main",
      status: "awaiting_user_action",
      uncertain: false,
    },
    {
      ...base,
      publication_id: 2,
      platform: "youtube",
      account_name: "Channel",
      status: "failed",
      uncertain: true,
    },
  ];

  render(<AssetUsage contentId={content.id} />);

  const list = await screen.findByRole("list", {
    name: "Publications of this asset",
  });
  const [tiktok, youtube] = within(list).getAllByRole("listitem");
  expect(within(tiktok).getByText("Ready in TikTok")).toBeInTheDocument();
  expect(within(tiktok).queryByText("Published")).toBeNull();
  expect(within(youtube).getByText("Uncertain")).toBeInTheDocument();
  expect(screen.getByText(/Last published:/)).toHaveTextContent("never");
});
