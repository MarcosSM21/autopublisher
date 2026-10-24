import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Project } from "../../types.ts";
import { setHealth, setViewport, urlPosts, writes } from "./test-publish.ts";

let api: FakeApi;
let project: Project;
let threads: Account;
let second: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  threads = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "studio",
  });
  second = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "news",
  });
  api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
  api.setThreadsConnection(threads.id);
  api.setThreadsConnection(second.id);
  // Text capability comes from account health (the backend), not a list here.
  setHealth(api, project.id);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openText(path = `/p/${project.id}/posts/new`) {
  const user = userEvent.setup();
  const view = renderRoute(path);
  await screen.findByRole("heading", { level: 1, name: "Text post" });
  return { user, ...view };
}

function destinations() {
  return screen.getByRole("group", { name: "Destinations" });
}

function textDraft(account: Account, text = "Hello") {
  return api.addPublication({
    content_id: null,
    account_id: account.id,
    description_override: text,
    hashtags_override: [],
  });
}

it("asks for the text and offers only accounts that post text; the rest need media", async () => {
  const { user } = await openText();
  await screen.findByRole("group", { name: "Destinations" });
  const yt = within(destinations()).getByRole("checkbox", { name: /YouTube/ });
  expect(yt).toBeDisabled();
  expect(within(destinations()).getByText("Needs media")).toBeInTheDocument();
  // No per-destination customization before Continue (plan C3).
  await user.click(
    within(destinations()).getByRole("checkbox", { name: /studio/ }),
  );
  expect(screen.queryByRole("button", { name: /^Customize/ })).toBeNull();

  await user.click(screen.getByRole("button", { name: "Continue" }));
  const summary = await screen.findByRole("alert");
  await user.click(
    within(summary).getByRole("link", { name: "Write the text of the post." }),
  );
  expect(screen.getByLabelText(/^Text/)).toHaveFocus();
  expect(writes(api)).toEqual([]);
});

it("Continue creates text drafts with the existing endpoint and names them in the URL", async () => {
  const { user, router } = await openText();
  await screen.findByRole("group", { name: "Destinations" });
  await user.type(screen.getByLabelText(/^Text/), "Big news");
  await user.type(screen.getByLabelText("Hashtags"), "#launch");
  await user.click(
    within(destinations()).getByRole("checkbox", { name: /studio/ }),
  );
  await user.click(
    within(destinations()).getByRole("checkbox", { name: /news/ }),
  );
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(
    await screen.findByRole("heading", { level: 2, name: "Review" }),
  ).toHaveFocus();
  expect(writes(api)).toEqual([
    {
      method: "POST",
      path: `/projects/${project.id}/text-publications`,
      body: {
        account_ids: [threads.id, second.id],
        description: "Big news",
        hashtags: ["#launch"],
      },
    },
  ]);
  expect(urlPosts(router)).toBe(
    api.publications.map((record) => record.id).join(","),
  );
});

it("a reload rebuilds the text set from ?posts=, dropping a Media post", async () => {
  const media = api.addContent({ project_id: project.id });
  const mediaPost = api.addPublication({
    content_id: media.id,
    account_id: threads.id,
  });
  const draft = textDraft(second);
  const { router } = await openText(
    `/p/${project.id}/posts/new?posts=${draft.id},${mediaPost.id}`,
  );
  expect(
    await screen.findByText("1 post couldn't be included."),
  ).toBeInTheDocument();
  expect(urlPosts(router)).toBe(String(draft.id));
  expect(screen.getAllByRole("region", { name: /^Threads/ })).toHaveLength(1);
  const content = screen.getByRole("region", {
    name: "Content by destination",
  });
  expect(within(content).getByText("Custom text")).toBeInTheDocument();
  expect(
    within(content).queryByRole("button", { name: /Use the media's caption/ }),
  ).toBeNull();
});

it("customizes one destination in Review with a PATCH", async () => {
  const a = textDraft(threads);
  const b = textDraft(second);
  const { user } = await openText(
    `/p/${project.id}/posts/new?posts=${a.id},${b.id}`,
  );
  const content = await screen.findByRole("region", {
    name: "Content by destination",
  });
  await user.click(
    within(content).getByRole("button", { name: "Customize Threads @news" }),
  );
  const dialog = await screen.findByRole("dialog");
  await user.clear(within(dialog).getByLabelText("Caption"));
  await user.type(within(dialog).getByLabelText("Caption"), "Only here");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));
  await within(content).findByText("Only here");
  expect(
    writes(api).map((request) => `${request.method} ${request.path}`),
  ).toEqual([`PATCH /publications/${b.id}`]);
});

it("Publish now runs the shared orchestration", async () => {
  const draft = textDraft(threads);
  const { user } = await openText(
    `/p/${project.id}/posts/new?posts=${draft.id}`,
  );
  await screen.findByRole("region", { name: /^Threads/ });
  await user.click(
    screen.getByRole("button", { name: "Publish to 1 destination" }),
  );
  const results = await screen.findByRole("region", { name: "Results" });
  expect(await within(results).findByText("1 publishing")).toBeInTheDocument();
  expect(writes(api).map((request) => request.path)).toEqual([
    `/publications/${draft.id}/publish`,
  ]);
});

it("Schedule arms each Post and shows a partial result", async () => {
  const a = textDraft(threads);
  const b = textDraft(second);
  api.failRequest("PATCH", `/publications/${b.id}`, 409, {
    error: {
      code: "account_inactive",
      message: "Reactivate the account first.",
    },
  });
  const { user } = await openText(
    `/p/${project.id}/posts/new?posts=${a.id},${b.id}`,
  );
  await screen.findAllByRole("region", { name: /^Threads/ });
  await user.click(screen.getByRole("radio", { name: "Schedule" }));
  fireEvent.change(screen.getByLabelText(/Date and time/), {
    target: { value: "2099-01-01T10:00" },
  });
  await user.click(screen.getByRole("button", { name: "Schedule 2 posts" }));
  const results = await screen.findByRole("region", { name: "Results" });
  expect(
    await within(results).findByText("1 scheduled · 1 still a draft"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Schedule 1 post" }),
  ).toBeInTheDocument();
});

it("Finish later leaves for Posts → Drafts, and Continue setup comes back to that draft", async () => {
  setViewport(1280);
  const draft = textDraft(threads);
  const { user, router } = await openText(
    `/p/${project.id}/posts/new?posts=${draft.id}`,
  );
  await screen.findByRole("region", { name: /^Threads/ });
  await user.click(screen.getByRole("button", { name: "Finish later" }));
  await waitFor(() =>
    expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`),
  );
  // The focus is moved in an effect after the list renders.
  const drafts = await screen.findByRole("heading", { name: "Drafts · 1" });
  await waitFor(() => expect(drafts).toHaveFocus());

  await user.click(screen.getByRole("link", { name: /Hello/ }));
  const status = await screen.findByRole("region", { name: "Status" });
  await user.click(
    within(status).getByRole("button", { name: "Continue setup" }),
  );
  expect(router.state.location.pathname).toBe(`/p/${project.id}/posts/new`);
  expect(urlPosts(router)).toBe(String(draft.id));
  expect(
    await screen.findByRole("heading", { level: 2, name: "Review" }),
  ).toBeInTheDocument();
  expect(writes(api)).toEqual([]);
});
