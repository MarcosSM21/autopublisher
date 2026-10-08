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
import { AUTOMATION_POLL_INTERVAL_MS } from "../utils.ts";
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

describe("automatic publishing (US1)", () => {
  function inMinutes(minutes: number) {
    return new Date(Date.now() + minutes * 60_000).toISOString();
  }

  it("shows whether each attempt was started manually or by the scheduler", async () => {
    const publication = addYouTubePublication({
      scheduled_at: inMinutes(5),
      auto_publish_enabled: true,
    });
    api.startScheduledAttempt(publication.id);
    api.failAttempt(
      publication.id,
      "network_error",
      "The connection was lost.",
    );
    const record = api.publications.find((p) => p.id === publication.id)!;
    api.startAttempt(record);
    api.succeedAttempt(publication.id);
    const { user } = renderDetail(api.publicationView(record));

    await user.click(await screen.findByText("Attempts (2)"));

    const history = screen.getByRole("list", { name: "Attempt history" });
    const items = within(history).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Started manually");
    expect(items[1]).toHaveTextContent("Started by scheduler");
  });

  it("refreshes an armed publication until the scheduler starts it", async () => {
    const publication = addYouTubePublication({
      scheduled_at: inMinutes(1),
      auto_publish_enabled: true,
    });
    renderDetail(publication);
    await screen.findByText("Scheduled");
    expect(polls(publication.id)).toBe(0);

    await tick(AUTOMATION_POLL_INTERVAL_MS);
    expect(polls(publication.id)).toBe(1);

    api.startScheduledAttempt(publication.id);
    await tick(AUTOMATION_POLL_INTERVAL_MS);
    expect(await screen.findByText("Publishing")).toBeInTheDocument();

    // From now on the faster polling of uploads applies.
    const before = polls(publication.id);
    await tick(POLL_INTERVAL_MS);
    expect(polls(publication.id)).toBe(before + 1);
  });

  it("does not poll a scheduled publication without auto-publish", async () => {
    const publication = addYouTubePublication({ scheduled_at: inMinutes(1) });
    renderDetail(publication);
    await screen.findByText("Scheduled");

    await tick(AUTOMATION_POLL_INTERVAL_MS * 3);

    expect(polls(publication.id)).toBe(0);
  });
});

describe("explicit consent (US2)", () => {
  function inMinutes(minutes: number) {
    return new Date(Date.now() + minutes * 60_000).toISOString();
  }

  function patchBodies() {
    return api.requests
      .filter((request) => request.method === "PATCH")
      .map((request) => request.body);
  }

  it("saves a schedule without auto-publish unless asked", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);

    await user.type(
      await screen.findByLabelText("Publish at"),
      "2100-03-15T18:45",
    );
    const consent = screen.getByRole("checkbox", {
      name: "Publish automatically at this time",
    });
    expect(consent).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save schedule" }));

    await waitFor(() =>
      expect(patchBodies()).toEqual([
        {
          scheduled_at: new Date(2100, 2, 15, 18, 45).toISOString(),
          auto_publish_enabled: false,
        },
      ]),
    );
  });

  it("schedules and enables auto-publish explicitly", async () => {
    const publication = addYouTubePublication();
    const { user } = renderDetail(publication);

    await user.type(
      await screen.findByLabelText("Publish at"),
      "2100-03-15T18:45",
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Publish automatically at this time",
      }),
    );
    expect(
      screen.getByText(
        "AutoPublisher will upload this publication automatically when the time comes. It must be running at that time.",
      ),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Schedule & enable auto-publish" }),
    );

    await waitFor(() =>
      expect(patchBodies()).toEqual([
        {
          scheduled_at: new Date(2100, 2, 15, 18, 45).toISOString(),
          auto_publish_enabled: true,
        },
      ]),
    );
  });

  it("keeps the current consent checked when editing an armed schedule", async () => {
    const publication = addYouTubePublication({
      scheduled_at: inMinutes(60),
      auto_publish_enabled: true,
    });
    renderDetail(publication);

    expect(
      await screen.findByRole("checkbox", {
        name: "Publish automatically at this time",
      }),
    ).toBeChecked();
  });

  it("enables auto-publish after a confirmation", async () => {
    const scheduledAt = inMinutes(60);
    const publication = addYouTubePublication({ scheduled_at: scheduledAt });
    const { user } = renderDetail(publication);
    expect(
      await screen.findByText("Auto-publish disabled"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Enable auto-publish" }),
    );
    const dialog = screen.getByRole("dialog", { name: "Enable auto-publish" });
    expect(dialog).toHaveTextContent("YouTube @cyberchannel");
    expect(patchBodies()).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Enable" }));

    await waitFor(() =>
      expect(patchBodies()).toEqual([{ auto_publish_enabled: true }]),
    );
    expect(await screen.findByText("Auto-publish enabled")).toBeInTheDocument();
  });

  it("disables auto-publish", async () => {
    const publication = addYouTubePublication({
      scheduled_at: inMinutes(60),
      auto_publish_enabled: true,
    });
    const { user } = renderDetail(publication);

    await user.click(
      await screen.findByRole("button", { name: "Disable auto-publish" }),
    );

    await waitFor(() =>
      expect(patchBodies()).toEqual([{ auto_publish_enabled: false }]),
    );
    expect(
      await screen.findByText("Auto-publish disabled"),
    ).toBeInTheDocument();
  });

  it("cannot enable auto-publish for a past date", async () => {
    const publication = addYouTubePublication({
      scheduled_at: new Date(Date.now() - 60_000).toISOString(),
    });
    renderDetail(publication);

    expect(
      await screen.findByRole("button", { name: "Enable auto-publish" }),
    ).toBeDisabled();
  });

  it("shows a reactivated publication as disarmed", async () => {
    const publication = addYouTubePublication({
      scheduled_at: inMinutes(60),
      auto_publish_enabled: true,
      status: "cancelled",
    });
    const { user, onChanged } = renderDetail(publication);

    await user.click(await screen.findByRole("button", { name: "Reactivate" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const record = api.publications.find((p) => p.id === publication.id)!;
    expect(api.publicationView(record).auto_publish_state).toBe("disabled");
  });
});

describe("automatic window (US3)", () => {
  const PAST = new Date(Date.now() - 60 * 60_000).toISOString();

  it("shows an armed publication that missed its window", async () => {
    const publication = addYouTubePublication({
      scheduled_at: PAST,
      auto_publish_enabled: true,
    });
    renderDetail(publication);

    expect(
      await screen.findByText("Missed automatic publishing window"),
    ).toBeInTheDocument();
    expect(screen.getByText("Publish now or reschedule")).toBeInTheDocument();
    expect(screen.getByText("Scheduled")).toBeInTheDocument();
    expect(await publishButton()).toBeEnabled();
    expect(screen.getByRole("form", { name: "Schedule" })).toBeInTheDocument();
  });

  it("never shows a disarmed past publication as missed", async () => {
    const publication = addYouTubePublication({ scheduled_at: PAST });
    renderDetail(publication);

    expect(
      await screen.findByText("Auto-publish disabled"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Missed automatic publishing window"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
  });
});

describe("paused automation (US4)", () => {
  it("shows that an armed publication waits for the automation to resume", async () => {
    api.automation = { ...api.automation, paused: true };
    const publication = addYouTubePublication({
      scheduled_at: new Date(Date.now() + 60 * 60_000).toISOString(),
      auto_publish_enabled: true,
    });
    renderDetail(publication);

    expect(await screen.findByText("Automation paused")).toBeInTheDocument();
    expect(screen.getByText("Auto-publish enabled")).toBeInTheDocument();
  });
});

describe("automatic start failures (US6)", () => {
  const ERROR = {
    code: "reconnect_required",
    message: "Reconnect the channel; nothing was uploaded.",
    failed_at: "2026-10-07T18:00:30Z",
  };

  it("shows why the publication could not start automatically", async () => {
    const publication = addYouTubePublication({
      scheduled_at: new Date(Date.now() - 60_000).toISOString(),
      auto_publish_enabled: true,
      auto_publish_error: ERROR,
    });
    renderDetail(publication);

    const alert = await screen.findByRole("alert", {
      name: "Automatic start failed",
    });
    expect(alert).toHaveTextContent(
      "Could not start automatically: Reconnect the channel; nothing was uploaded.",
    );
  });

  it("keeps the reason next to a missed window", async () => {
    const publication = addYouTubePublication({
      scheduled_at: new Date(Date.now() - 60 * 60_000).toISOString(),
      auto_publish_enabled: true,
      auto_publish_error: ERROR,
    });
    renderDetail(publication);

    expect(
      await screen.findByText("Missed automatic publishing window"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("alert", { name: "Automatic start failed" }),
    ).toBeInTheDocument();
  });

  it("shows nothing without a failure", async () => {
    const publication = addYouTubePublication({
      scheduled_at: new Date(Date.now() + 60_000).toISOString(),
      auto_publish_enabled: true,
    });
    renderDetail(publication);

    await screen.findByText("Auto-publish enabled");
    expect(
      screen.queryByRole("alert", { name: "Automatic start failed" }),
    ).not.toBeInTheDocument();
  });
});
