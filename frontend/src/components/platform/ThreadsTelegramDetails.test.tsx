import { cleanup, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Project } from "../../types.ts";
import { card, renderCard, writes } from "./test-card.tsx";

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

it("Threads saves the optional alt text on blur", async () => {
  const image = api.addContent({ project_id: project.id });
  const account = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "l4i4",
  });
  api.setThreadsConnection(account.id);
  const publication = api.addPublication({
    content_id: image.id,
    account_id: account.id,
  });
  const { user } = renderCard(publication);
  const region = card(/Threads/);
  await within(region).findByText("Ready");

  // Ready starts collapsed.
  await user.click(within(region).getByRole("button", { name: "Details" }));
  await user.type(within(region).getByLabelText("Alt text"), "A chart");
  await user.tab();
  await within(region).findByText("Saved");
  expect(writes(api)).toEqual([
    {
      method: "PUT",
      path: `/publications/${publication.id}/threads-options`,
      body: { alt_text: "A chart" },
    },
  ]);
});

it.each([
  ["with a channel", true, "Ready", "Posts to Test channel"],
  ["without a channel", false, "Blocked", "Choose a channel"],
])("Telegram %s", async (_label, withChannel, state, text) => {
  const account = api.addAccount({
    project_id: project.id,
    platform: "telegram",
    handle: "l4i4",
  });
  if (withChannel) {
    api.setTelegramConnection(account.id);
  } else {
    api.setTelegramConnection(account.id, null);
  }
  const publication = api.addPublication({
    content_id: null,
    account_id: account.id,
    description_override: "Hello",
  });
  renderCard(publication);
  const region = card(/Telegram/);

  expect(await within(region).findByText(state)).toBeInTheDocument();
  expect(within(region).getAllByText(text)[0]).toBeInTheDocument();
  if (!withChannel) {
    expect(
      within(region).getByRole("link", { name: "Choose a channel" }),
    ).toHaveAttribute("href", `/p/${project.id}/accounts/${account.id}`);
  }
});
