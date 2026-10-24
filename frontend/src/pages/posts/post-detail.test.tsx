import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Content, Project, Publication } from "../../types.ts";
import {
  addTelegram,
  setHealth,
  setViewport,
} from "../publish/test-publish.ts";

let api: FakeApi;
let project: Project;
let media: Content;
let youtube: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  setViewport(1280);
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    title: "Teaser",
    description: "Media caption",
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openDetail(post: Publication) {
  setHealth(api, project.id);
  const user = userEvent.setup();
  const view = renderRoute(`/p/${project.id}/posts/${post.id}`);
  const detail = await screen.findByRole("region", { name: "Post details" });
  return { user, detail, ...view };
}

function panel() {
  return screen.getByRole("region", { name: "Status" });
}

it("shows header, state and actions, When, Content, Platform details, Activity and Cancel, in that order", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    scheduled_at: "2099-01-01T10:00:00Z",
    auto_publish_enabled: true,
  });
  const { detail } = await openDetail(post);
  const order = [
    within(detail).getByText(/Media post · YouTube @chan/),
    panel(),
    within(detail).getByRole("heading", { name: "When" }),
    within(detail).getByRole("heading", { name: "Content" }),
    within(detail).getByRole("heading", { name: "Platform details" }),
    within(detail).getByRole("heading", { name: "Activity" }),
    within(detail).getByRole("button", { name: "Cancel post" }),
  ];
  for (let index = 1; index < order.length; index += 1) {
    expect(
      order[index - 1].compareDocumentPosition(order[index]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  }
  expect(
    within(panel()).getByText("Scheduled · automatic"),
  ).toBeInTheDocument();
  expect(
    within(panel()).getByRole("button", { name: "Edit schedule" }),
  ).toBeInTheDocument();
  expect(
    within(panel()).getByRole("button", { name: "Publish now" }),
  ).toBeInTheDocument();
});

it.each([
  ["a Draft with Media", {}, ["Continue in Publish"]],
  [
    "a legacy manual schedule",
    { scheduled_at: "2099-01-01T10:00:00Z" },
    ["Publish automatically", "Publish now"],
  ],
  [
    "a missed Post",
    { scheduled_at: "2020-01-01T10:00:00Z" },
    ["Reschedule", "Publish now"],
  ],
  [
    "a Failed Post",
    { status: "failed" as const },
    ["Retry now", "Reschedule", "Move to drafts"],
  ],
  ["a cancelled Post", { status: "cancelled" as const }, ["Reactivate"]],
])("panel for %s", async (_, values, buttons) => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    ...values,
  });
  await openDetail(post);
  expect(
    within(panel())
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(buttons);
});

it("a Needs review Post only offers Check result", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.failAttempt(post.id, "timeout", "No answer.", false);
  await openDetail(post);
  expect(
    within(panel())
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Check result"]);
  expect(
    screen.queryByRole("button", { name: /Reschedule|Move to drafts|Retry/ }),
  ).toBeNull();
});

it("updates in place when the state changes, without remounting", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
  });
  const { user } = await openDetail(post);
  await user.click(screen.getByRole("button", { name: /Show activity/ }));
  expect(
    await screen.findByText("Nothing has been sent yet."),
  ).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Cancel post" }));
  await user.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Cancel post",
    }),
  );
  expect(await within(panel()).findByText("Cancelled")).toBeInTheDocument();
  // The list was read again and the Activity disclosure stayed open.
  await waitFor(() =>
    expect(
      api.requests.filter(
        (request) => request.path === `/projects/${project.id}/publications`,
      ).length,
    ).toBeGreaterThan(1),
  );
  expect(screen.getByRole("button", { name: /Show activity/ })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});

it("Platform details: open when something is missing (Complete details focuses it), folded when Published", async () => {
  const soon = new Date(Date.now() + 2 * 86_400_000).toISOString();
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    scheduled_at: soon,
    auto_publish_enabled: true,
  });
  api.projectOverviews.set(project.id, {
    ...api.emptyOverview([project]),
    attention: [
      {
        kind: "incomplete",
        priority: 6,
        project: { id: project.id, name: project.name },
        account: {
          id: youtube.id,
          platform: "youtube",
          label: "YouTube @chan",
        },
        post: {
          id: post.id,
          display_state: "scheduled_automatic",
          scheduled_at: soon,
          media_title: null,
          excerpt: null,
        },
        title: "Needs details before publishing",
        detail: "Declare whether the video is made for kids.",
        at: soon,
        action: { label: "Complete", target: { type: "post", id: post.id } },
        affected_posts: 0,
      },
    ],
  });
  const { user } = await openDetail(post);
  const card = await screen.findByRole("region", { name: /^YouTube/ });
  await within(card).findByText("Details needed");
  expect(within(card).getByRole("button", { name: "Details" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await user.click(
    within(panel()).getByRole("button", { name: "Complete details" }),
  );
  await waitFor(() => expect(card.contains(document.activeElement)).toBe(true));
  cleanup();

  const published = api.addPublication({
    content_id: media.id,
    account_id: addTelegram(api, project.id, "news").id,
    status: "published",
    published_at: "2026-10-01T10:00:00Z",
  });
  await openDetail(published);
  const folded = await screen.findByRole("region", { name: /^Telegram/ });
  expect(
    within(folded).getByRole("button", { name: "Details" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(within(folded).queryByText(/Ready|Blocked|Details needed/)).toBeNull();
});

it("a Published Post shows what was sent, even if the Media changed since", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.publicationAttempts.get(post.id)!.at(-1)!.submitted = {
    title: "Sent title",
    description: "Sent description",
  };
  api.succeedAttempt(post.id);
  media.description = "Edited later";
  const { user } = await openDetail(post);
  const content = screen
    .getByRole("heading", { name: "Content" })
    .closest("section")!;
  expect(within(content).getByText("Sent title")).toBeInTheDocument();
  expect(within(content).getByText("Sent description")).toBeInTheDocument();
  await user.click(
    within(content).getByRole("button", { name: "Current text" }),
  );
  expect(within(content).getByText("Edited later")).toBeInTheDocument();
});

it("Telegram falls back to the current text, saying it may differ", async () => {
  const telegram = addTelegram(api, project.id, "news");
  const post = api.addPublication({
    content_id: media.id,
    account_id: telegram.id,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.succeedAttempt(post.id);
  await openDetail(post);
  expect(
    screen.getByText(
      "This is the current text. It may differ from what was sent.",
    ),
  ).toBeInTheDocument();
});

it("cancels after a confirmation and reactivates with the existing endpoint", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
  });
  const { user } = await openDetail(post);
  await user.click(screen.getByRole("button", { name: "Cancel post" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Cancel this post?",
  });
  expect(dialog).toHaveTextContent("You can reactivate it later.");
  expect(api.publications[0].status).toBe("unscheduled");
  await user.click(within(dialog).getByRole("button", { name: "Cancel post" }));
  expect(await within(panel()).findByText("Cancelled")).toBeInTheDocument();

  await user.click(within(panel()).getByRole("button", { name: "Reactivate" }));
  expect(await within(panel()).findByText("Draft")).toBeInTheDocument();
  const reactivations = api.requests.filter((request) =>
    request.path.endsWith("/reactivate"),
  );
  expect(reactivations).toHaveLength(1);
  // Reactivate never arms anything.
  expect(api.publications[0].auto_publish_enabled).toBe(false);
});

it("on phones the primary action sits in the sticky bar of the detail page", async () => {
  setViewport(375);
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "failed",
  });
  await openDetail(post);
  expect(
    within(panel()).queryByRole("button", { name: "Retry now" }),
  ).toBeNull();
  const bar = screen.getByRole("group", { name: /actions$/ });
  expect(bar).toHaveClass("ap-page-actions--sticky");
  expect(
    within(bar).getByRole("button", { name: "Retry now" }),
  ).toBeInTheDocument();
});

it("Needs action (TikTok inbox) checks its status from the panel", async () => {
  const tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyber",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: tiktok.id,
  });
  api.tiktokOptions.set(post.id, {
    mode: "INBOX_UPLOAD",
    privacy_level: null,
    allow_comment: false,
    allow_duet: false,
    allow_stitch: false,
    commercial_disclosure_enabled: false,
    brand_organic_toggle: false,
    brand_content_toggle: false,
    is_aigc: null,
  });
  api.startAttempt(api.publications.find((record) => record.id === post.id)!);
  api.deliverToInbox(post.id);
  const { user } = await openDetail(post);
  const check = await within(panel()).findByRole("button", {
    name: "Check status",
  });
  await user.click(check);
  expect(
    api.requests.some(
      (request) => request.path === `/publications/${post.id}/check-status`,
    ),
  ).toBe(true);
});

it("as a phone page, the headings never skip a level", async () => {
  setViewport(375);
  const project = api.addProject({ name: "Headings" });
  const media = api.addContent({ project_id: project.id, title: "Teaser" });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "h",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: account.id,
  });
  setHealth(api, project.id);
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  await screen.findByRole("region", { name: "Post details" });

  const levels = screen
    .getAllByRole("heading")
    .map((heading) => Number(heading.tagName.slice(1)));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Posts");
  expect(
    screen.getByRole("heading", { level: 2, name: "Teaser" }),
  ).toBeVisible();
  levels.slice(1).forEach((level, index) => {
    expect(level - levels[index]).toBeLessThanOrEqual(1);
  });
});

describe("Delete post", () => {
  function scheduled() {
    return api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
      scheduled_at: "2099-01-01T10:00:00Z",
      auto_publish_enabled: true,
    });
  }

  function published() {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    api.startAttempt(api.publications.find((r) => r.id === post.id)!);
    api.succeedAttempt(post.id);
    return post;
  }

  function needsReview() {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    api.startAttempt(api.publications.find((r) => r.id === post.id)!);
    api.failAttempt(post.id, "timeout", "No answer.", false);
    return post;
  }

  function failed() {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    api.startAttempt(api.publications.find((r) => r.id === post.id)!);
    api.failAttempt(post.id, "upload_failed", "Rejected.", true);
    return post;
  }

  function missed() {
    return api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
      scheduled_at: "2020-01-01T10:00:00Z",
      auto_publish_enabled: false,
    });
  }

  it.each([
    [
      "Draft",
      () =>
        api.addPublication({ content_id: media.id, account_id: youtube.id }),
      null,
    ],
    ["Scheduled", scheduled, "This post will not be published."],
    ["Failed", failed, null],
    ["Missed", missed, null],
    [
      "Published",
      published,
      "It will only be removed from AutoPublisher. The content published on YouTube is not affected.",
    ],
    [
      "Needs review",
      needsReview,
      "This post may have been published. Check YouTube before publishing this media again.",
    ],
  ])(
    "a %s Post shows the backend's summary and disappears after Delete",
    async (_label, make, summary) => {
      const post = make();
      const { user, detail, router } = await openDetail(post);
      await user.click(
        within(detail).getByRole("button", { name: "Delete post" }),
      );
      const dialog = screen.getByRole("dialog", { name: "Delete post?" });
      const confirm = await within(dialog).findByRole("button", {
        name: "Delete",
      });
      if (summary) {
        expect(dialog).toHaveTextContent(summary);
      }
      await user.click(confirm);

      expect(router.state.location.pathname).toBe(`/p/${project.id}/posts`);
      expect(await screen.findByText("Post deleted.")).toBeInTheDocument();
      expect(
        screen.queryByRole("region", { name: "Post details" }),
      ).not.toBeInTheDocument();
      await waitFor(() =>
        expect(
          screen.getByRole("heading", { name: "No posts yet" }),
        ).toBeInTheDocument(),
      );
      expect(api.publications).toHaveLength(0);
    },
  );

  it("is a secondary action, apart from the primary one", async () => {
    const { detail } = await openDetail(scheduled());
    const button = within(detail).getByRole("button", { name: "Delete post" });
    expect(button).not.toHaveClass("ap-button--primary");
    expect(button).not.toHaveClass("ap-button--danger");
    expect(button).toHaveClass("ap-delete-entry");
  });

  it("is disabled while publishing, and the backend still blocks it", async () => {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
    });
    api.startAttempt(api.publications.find((r) => r.id === post.id)!);
    const { detail } = await openDetail(post);
    const button = within(detail).getByRole("button", { name: "Delete post" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(
      "This post is being published right now.",
    );
  });

  it("reloads the list and the project overview, leaving no ghost row", async () => {
    const kept = scheduled();
    const gone = published();
    const { user, detail } = await openDetail(gone);
    await user.click(
      within(detail).getByRole("button", { name: "Delete post" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Delete post?" });
    const before = api.requests.length;
    await user.click(
      await within(dialog).findByRole("button", { name: "Delete" }),
    );

    await waitFor(() =>
      expect(
        api.requests
          .slice(before)
          .filter((r) => r.path === `/overview?project_id=${project.id}`),
      ).not.toHaveLength(0),
    );
    expect(document.querySelector(`[data-detail-id="${gone.id}"]`)).toBeNull();
    expect(
      document.querySelector(`[data-detail-id="${kept.id}"]`),
    ).not.toBeNull();
  });
});
