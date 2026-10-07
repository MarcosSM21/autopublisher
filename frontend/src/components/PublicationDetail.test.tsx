import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Project, Publication } from "../types.ts";
import PublicationDetail, { POLL_INTERVAL_MS } from "./PublicationDetail.tsx";

let api: FakeApi;
let project: Project;
let video: Content;
let youtube: Account;

const COMPLETE_OPTIONS = {
  privacy_status: "private" as const,
  made_for_kids: false,
  contains_synthetic_media: false,
  notify_subscribers: false,
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    original_filename: "intro.mp4",
    title: "Cybersecurity basics",
    size_bytes: 4_000_000,
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "cyberchannel",
  });
  api.setConnection(youtube.id);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function addYouTubePublication(values: Record<string, unknown> = {}) {
  const publication = api.addPublication({
    content_id: video.id,
    account_id: youtube.id,
    ...values,
  });
  api.youtubeOptions.set(publication.id, COMPLETE_OPTIONS);
  return publication;
}

function renderDetail(publication: Publication) {
  const onChanged = vi.fn(async () => {});
  render(<PublicationDetail publication={publication} onChanged={onChanged} />);
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  return { user, onChanged };
}

async function tick(ms = POLL_INTERVAL_MS) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function publishRequests() {
  return api.requests.filter((request) => request.path.endsWith("/publish"));
}

function polls(publicationId: number) {
  return api.requests.filter(
    (request) =>
      request.method === "GET" &&
      request.path === `/publications/${publicationId}`,
  ).length;
}

async function publishButton() {
  const button = await screen.findByRole("button", { name: "Publish now" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await publishButton());
  const dialog = await screen.findByRole("dialog", { name: "Publish now" });
  await waitFor(() =>
    expect(
      within(dialog).getByRole("button", { name: "Publish" }),
    ).toBeEnabled(),
  );
  return dialog;
}

describe("publish now", () => {
  it("offers Publish now and shows the confirmation summary", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);

    const dialog = await openDialog(user);

    for (const [label, value] of [
      ["Title", "Cybersecurity basics"],
      ["Channel", "Cyber Channel (UC_TEST_1)"],
      ["Privacy", "private"],
      ["Notify subscribers", "No"],
      ["File", "intro.mp4"],
    ]) {
      expect(within(dialog).getByText(label)).toBeInTheDocument();
      expect(within(dialog).getByText(value)).toBeInTheDocument();
    }
  });

  it("does nothing when the confirmation is cancelled", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);

    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(publishRequests()).toHaveLength(0);
  });

  it("publishes once even on a double click", async () => {
    const publication = addYouTubePublication();
    const { user, onChanged } = renderDetail(publication);

    const dialog = await openDialog(user);
    const confirm = within(dialog).getByRole("button", { name: "Publish" });
    await user.dblClick(confirm);

    expect(publishRequests()).toHaveLength(1);
    expect(await screen.findByText("Publishing")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("polls while publishing, shows progress and then the result", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    expect(
      await screen.findByRole("progressbar", { name: "Upload progress" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel publication" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Schedule" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Metadata" }),
    ).not.toBeInTheDocument();

    api.progressAttempt(publication.id, 2_000_000);
    await tick();
    expect(await screen.findByText(/50%/)).toBeInTheDocument();

    api.succeedAttempt(publication.id, { processing: "processing" });
    await tick();
    const link = await screen.findByRole("link", { name: "Open on YouTube" });
    expect(link).toHaveAttribute(
      "href",
      "https://www.youtube.com/watch?v=FakeVid_001",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText(/Privacy on YouTube/)).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();

    const before = polls(publication.id);
    await tick(POLL_INTERVAL_MS * 3);
    expect(polls(publication.id)).toBe(before);
  });

  it("does not offer editing for a published publication", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    api.succeedAttempt(publication.id);
    await tick();

    expect(
      await screen.findByRole("link", { name: "Open on YouTube" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Publish now" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel publication" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Metadata" }),
    ).not.toBeInTheDocument();
  });
});

describe("publish check problems", () => {
  it("disables Publish now and lists why", async () => {
    const publication = addYouTubePublication();
    api.publishChecks.set(publication.id, {
      eligible: false,
      problems: [
        {
          code: "content_not_video",
          message: "YouTube only accepts video content.",
          field: null,
        },
        {
          code: "invalid_metadata",
          message: "The title must be at most 100 characters for YouTube.",
          field: "title",
        },
      ],
    });
    renderDetail(publication);

    const problems = await screen.findByRole("list", {
      name: "Why this cannot be published",
    });
    expect(
      within(problems).getByText("YouTube only accepts video content."),
    ).toBeInTheDocument();
    expect(
      within(problems).getByText(
        "The title must be at most 100 characters for YouTube.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish now" })).toBeDisabled();
  });

  it("reloads the check after saving the YouTube options", async () => {
    const publication = api.addPublication({
      content_id: video.id,
      account_id: youtube.id,
    });
    const { user } = renderDetail(publication);

    expect(
      await screen.findByText(
        "Declare whether the video is made for kids and whether it contains altered or synthetic content.",
      ),
    ).toBeInTheDocument();
    for (const name of ["Made for kids", "Altered or synthetic content"]) {
      await user.click(
        within(screen.getByRole("group", { name })).getByRole("radio", {
          name: "No",
        }),
      );
    }
    await user.click(
      screen.getByRole("button", { name: "Save YouTube options" }),
    );

    await publishButton();
    expect(
      screen.queryByRole("list", { name: "Why this cannot be published" }),
    ).not.toBeInTheDocument();
  });
});

describe("failed executions", () => {
  async function failedPublication(determined: boolean) {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    api.failAttempt(
      publication.id,
      "network_error",
      "The connection to YouTube was lost.",
      determined,
    );
    await tick();
    return { publication, user };
  }

  it("shows the last error, the history and allows publishing again", async () => {
    await failedPublication(true);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(
      screen.getByText("The connection to YouTube was lost."),
    ).toBeInTheDocument();
    const history = await screen.findByRole("list", {
      name: "Attempt history",
    });
    expect(
      within(history).getByText(/network_error: The connection to YouTube/),
    ).toBeInTheDocument();
    await publishButton();
    expect(screen.queryByText("Check YouTube Studio")).not.toBeInTheDocument();
  });

  it("asks for a manual review after an uncertain outcome", async () => {
    const { publication, user } = await failedPublication(false);

    const review = (await screen.findByText("Check YouTube Studio"))
      .parentElement!;
    expect(
      within(review).getByText("Cyber Channel (UC_TEST_1)"),
    ).toBeInTheDocument();
    expect(
      within(review).getByText("Cybersecurity basics"),
    ).toBeInTheDocument();
    expect(within(review).getByText("Time")).toBeInTheDocument();

    await user.click(await publishButton());
    const dialog = await screen.findByRole("dialog", { name: "Publish now" });
    const checkbox = await within(dialog).findByRole("checkbox", {
      name: "I checked YouTube Studio and this video was not published",
    });
    const confirm = within(dialog).getByRole("button", { name: "Publish" });
    expect(confirm).toBeDisabled();

    await user.click(checkbox);
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    const requests = publishRequests();
    expect(requests).toHaveLength(2);
    expect(requests[1].body).toEqual({ confirm_remote_checked: true });
    expect(api.publicationAttempts.get(publication.id)).toHaveLength(2);
  });
});

describe("scheduled publications", () => {
  const FUTURE = "2100-01-01T10:00:00.000Z";

  it("warns that a scheduled publication is published before its time", async () => {
    const publication = addYouTubePublication({
      status: "scheduled",
      scheduled_at: FUTURE,
    });
    const { user } = renderDetail(publication);

    const dialog = await openDialog(user);

    expect(
      within(dialog).getByText(
        `This publication is scheduled for ${new Date(FUTURE).toLocaleString()}. It will be published now, before its scheduled time.`,
      ),
    ).toBeInTheDocument();
  });

  it("keeps the original date as history once published", async () => {
    const publication = addYouTubePublication({
      status: "scheduled",
      scheduled_at: FUTURE,
    });
    const { user } = renderDetail(publication);
    const dialog = await openDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    api.succeedAttempt(publication.id);
    await tick();

    expect(
      await screen.findByText(
        `Was scheduled for ${new Date(FUTURE).toLocaleString()}`,
      ),
    ).toBeInTheDocument();
  });
});
