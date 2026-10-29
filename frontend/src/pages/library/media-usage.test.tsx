import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { PublicationStatus } from "../../types.ts";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function group(name: RegExp) {
  return screen.getByRole("region", { name });
}

it("groups the Posts by visible state, with Show all and links to each Post", async () => {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id, title: "Clip" });
  let handle = 0;
  function post(
    status: PublicationStatus,
    values: { scheduled_at?: string; published_at?: string } = {},
  ) {
    const account = api.addAccount({
      project_id: project.id,
      platform: "youtube",
      handle: `chan${(handle += 1)}`,
    });
    return api.addPublication({
      content_id: media.id,
      account_id: account.id,
      status,
      ...values,
    });
  }
  const failed = post("failed");
  post("scheduled", { scheduled_at: "2020-01-01T10:00:00Z" }); // missed
  post("awaiting_user_action");
  post("scheduled", { scheduled_at: "2099-01-01T10:00:00Z" });
  post("unscheduled");
  for (const day of ["01", "02", "03", "04"]) {
    post("published", { published_at: `2026-09-${day}T10:00:00Z` });
  }
  post("cancelled");
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/library/${media.id}`);

  const needsYou = await screen.findByRole("region", { name: "Needs you · 3" });
  expect(
    within(needsYou)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual([
    expect.stringContaining("Failed"),
    expect.stringContaining("Missed"),
    expect.stringContaining("Needs action"),
  ]);
  expect(
    within(group(/^Upcoming · 1/)).getByText("Scheduled · manual"),
  ).toBeVisible();
  expect(within(group(/^Drafts · 1/)).getByText("Draft")).toBeVisible();
  expect(screen.getByText("1 cancelled post")).toBeInTheDocument();

  const published = group(/^Published · 4/);
  const rows = () =>
    within(within(published).getByRole("list")).getAllByRole("link");
  expect(rows()).toHaveLength(3);
  // Latest first.
  expect(rows()[0]).toHaveTextContent("chan9");
  await user.click(
    within(published).getByRole("button", { name: "Show all 4" }),
  );
  expect(rows()).toHaveLength(4);
  // Published media lead to their metrics, side by side (Feature 027).
  expect(
    within(published).getByRole("link", {
      name: "See its metrics side by side",
    }),
  ).toHaveAttribute("href", `/p/${project.id}/analytics/media/${media.id}`);

  expect(within(needsYou).getByRole("link", { name: /chan1/ })).toHaveAttribute(
    "href",
    `/p/${project.id}/posts/${failed.id}`,
  );
});

it("says Not used yet when the Media has no Posts", async () => {
  const project = api.addProject({ name: "L4i4" });
  const media = api.addContent({ project_id: project.id, title: "Fresh" });
  renderRoute(`/p/${project.id}/library/${media.id}`);

  const usage = await screen.findByRole("region", { name: "Usage" });
  expect(await within(usage).findByText("Not used yet.")).toBeInTheDocument();
});
