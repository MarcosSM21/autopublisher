import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Account, Content, Project, Publication } from "../../types.ts";
import { toDateTimeLocalValue } from "../../utils.ts";
import { setHealth, setViewport, writes } from "../publish/test-publish.ts";
import ActionDialog, { type DialogAction } from "./ActionDialog.tsx";

let api: FakeApi;
let project: Project;
let media: Content;
let youtube: Account;

const FUTURE = "2099-01-01T10:00";

beforeEach(() => {
  api = new FakeApi();
  api.install();
  setViewport(1280);
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
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

async function open(post: Publication, action: string) {
  setHealth(api, project.id);
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/posts/${post.id}`);
  const status = await screen.findByRole("region", { name: "Status" });
  await user.click(within(status).getByRole("button", { name: action }));
  const dialog = await screen.findByRole("dialog", { name: action });
  return { user, dialog };
}

function patches() {
  return writes(api).filter((request) => request.method === "PATCH");
}

it("Failed → Reschedule arms the new time, keeping the history", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "failed",
  });
  const { user, dialog } = await open(post, "Reschedule");
  expect(within(dialog).getByText(/Time zone:/)).toBeInTheDocument();
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: FUTURE },
  });
  await user.click(within(dialog).getByRole("button", { name: "Reschedule" }));
  expect(
    await screen.findByText("Scheduled · automatic", {
      selector: ".ap-status-panel *",
    }),
  ).toBeInTheDocument();
  expect(patches()).toEqual([
    {
      method: "PATCH",
      path: `/publications/${post.id}`,
      body: {
        scheduled_at: new Date(FUTURE).toISOString(),
        auto_publish_enabled: true,
      },
    },
  ]);
});

it("Failed → Move to drafts sends scheduled_at null", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "failed",
  });
  const { user, dialog } = await open(post, "Move to drafts");
  await user.click(
    within(dialog).getByRole("button", { name: "Move to drafts" }),
  );
  expect(
    await screen.findByText("Draft", { selector: ".ap-status-panel *" }),
  ).toBeInTheDocument();
  expect(patches().map((request) => request.body)).toEqual([
    { scheduled_at: null },
  ]);
});

it("a past date is rejected inline, writing nothing", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "failed",
  });
  const { user, dialog } = await open(post, "Reschedule");
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: "2020-01-01T10:00" },
  });
  await user.click(within(dialog).getByRole("button", { name: "Reschedule" }));
  expect(
    within(dialog).getByText("Choose a date and time in the future."),
  ).toBeInTheDocument();
  expect(patches()).toEqual([]);
});

it("TikTok Direct Post: one declaration, recorded right before the PATCH", async () => {
  const tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyber",
  });
  const post = api.addPublication({
    content_id: media.id,
    account_id: tiktok.id,
    status: "failed",
  });
  api.tiktokOptions.set(post.id, {
    mode: "DIRECT_POST",
    privacy_level: "SELF_ONLY",
    allow_comment: false,
    allow_duet: false,
    allow_stitch: false,
    commercial_disclosure_enabled: false,
    brand_organic_toggle: false,
    brand_content_toggle: false,
    is_aigc: false,
  });
  const { user, dialog } = await open(post, "Reschedule");
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: FUTURE },
  });
  await user.click(within(dialog).getByRole("button", { name: "Reschedule" }));
  expect(
    within(dialog).getByText("Confirm the TikTok declaration first."),
  ).toBeInTheDocument();
  expect(writes(api)).toEqual([]);
  // Exactly one declaration on the page: the card in the detail shows none.
  const boxes = screen.getAllByRole("checkbox", {
    name: /I agree to the declaration/,
  });
  expect(boxes).toHaveLength(1);
  await user.click(boxes[0]);
  await user.click(within(dialog).getByRole("button", { name: "Reschedule" }));
  await screen.findByText("Scheduled · automatic", {
    selector: ".ap-status-panel *",
  });
  expect(
    writes(api).map((request) => `${request.method} ${request.path}`),
  ).toEqual([
    `POST /publications/${post.id}/tiktok-consent`,
    `PATCH /publications/${post.id}`,
  ]);
});

it("Edit schedule on a paused Post keeps it automatic and warns about the pause", async () => {
  api.automation.paused = true;
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    scheduled_at: "2099-01-01T08:00:00Z",
    auto_publish_enabled: true,
  });
  const { user, dialog } = await open(post, "Edit schedule");
  expect(within(dialog).getByLabelText(/Date and time/)).not.toHaveValue("");
  expect(within(dialog).getByText(/Automation is paused/)).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: "Edit schedule" }),
  );
  expect(
    await screen.findByText("Scheduled · paused", {
      selector: ".ap-status-panel *",
    }),
  ).toBeInTheDocument();
  expect(patches()[0].body).toMatchObject({ auto_publish_enabled: true });
});

it("Publish automatically arms a legacy manual schedule", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    scheduled_at: "2099-01-01T08:00:00Z",
  });
  const { user, dialog } = await open(post, "Publish automatically");
  await user.click(
    within(dialog).getByRole("button", { name: "Publish automatically" }),
  );
  expect(
    await screen.findByText("Scheduled · automatic", {
      selector: ".ap-status-panel *",
    }),
  ).toBeInTheDocument();
  expect(patches().map((request) => request.body)).toEqual([
    { auto_publish_enabled: true },
  ]);
});

it.each([
  ["with the Post to check", true],
  ["without one", false],
])(
  "an unexpected check_result_first says so and never retries (%s)",
  async (_, related) => {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
      status: "failed",
    });
    if (related) {
      // An uncertain attempt on another Post of the same Media and account.
      const other = api.addPublication({
        content_id: media.id,
        account_id: youtube.id,
        status: "cancelled",
      });
      api.startAttempt(
        api.publications.find((record) => record.id === other.id)!,
      );
      api.failAttempt(other.id, "timeout", "No answer.", false);
    }
    api.failRequest("PATCH", `/publications/${post.id}`, 409, {
      error: { code: "check_result_first", message: "Check the result first." },
    });
    const { user, dialog } = await open(post, "Move to drafts");
    await user.click(
      within(dialog).getByRole("button", { name: "Move to drafts" }),
    );
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Check the result first.");
    if (related) {
      const uncertain = api.publications.find(
        (record) => record.id !== post.id,
      )!;
      expect(
        within(alert).getByRole("link", { name: "Check result" }),
      ).toHaveAttribute("href", `/p/${project.id}/posts/${uncertain.id}`);
    } else {
      expect(
        within(alert).getByRole("link", { name: "Find it in Needs you" }),
      ).toBeInTheDocument();
    }
    expect(patches()).toHaveLength(1);
  },
);

// The props Calendar uses (Feature 024): `initialAt` and `onFailed`.

function renderDialog(
  post: Publication,
  action: DialogAction,
  props: { initialAt?: string; onFailed?: () => void } = {},
) {
  const onDone = vi.fn();
  render(
    <MemoryRouter>
      <ActionDialog
        action={action}
        post={post}
        posts={[post]}
        paused={false}
        onClose={() => {}}
        onDone={onDone}
        {...props}
      />
    </MemoryRouter>,
  );
  return { onDone, dialog: screen.getByRole("dialog", { name: /./ }) };
}

it.each([
  ["Edit schedule of a future date", "edit_schedule", "2099-01-01T08:00:00Z"],
  ["Edit schedule of a past date", "edit_schedule", "2020-01-01T08:00:00Z"],
  ["Reschedule", "reschedule", "2020-01-01T08:00:00Z"],
] as const)("initialAt replaces the initial value: %s", (_, action, date) => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    scheduled_at: date,
    auto_publish_enabled: true,
  });
  const initialAt = "2099-03-04T17:30:00Z";
  const { dialog } = renderDialog(post, action, { initialAt });
  expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue(
    toDateTimeLocalValue(initialAt),
  );
});

it.each([
  ["Edit schedule of a future date", "edit_schedule", "2099-01-01T08:00:00Z"],
  ["Edit schedule of a past date", "edit_schedule", "2020-01-01T08:00:00Z"],
  ["Reschedule", "reschedule", "2099-01-01T08:00:00Z"],
] as const)(
  "without initialAt the existing rule holds: %s",
  (_, action, date) => {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
      scheduled_at: date,
      auto_publish_enabled: true,
    });
    const { dialog } = renderDialog(post, action);
    expect(within(dialog).getByLabelText(/Date and time/)).toHaveValue(
      action === "edit_schedule" && date.startsWith("2099")
        ? toDateTimeLocalValue(date)
        : "",
    );
  },
);

it.each([
  [
    "409",
    409,
    {
      error: {
        code: "publication_not_editable",
        message: "This publication is being published and cannot be changed.",
      },
    },
    "This publication is being published",
  ],
  [
    "422",
    422,
    {
      error: {
        code: "validation_error",
        message: "Choose a date and time in the future.",
      },
    },
    "Choose a date and time in the future.",
  ],
])(
  "onFailed is called after a %s, with the error still shown",
  async (_, status, body, text) => {
    const post = api.addPublication({
      content_id: media.id,
      account_id: youtube.id,
      status: "failed",
    });
    api.failRequest("PATCH", `/publications/${post.id}`, status, body);
    const onFailed = vi.fn();
    const { dialog, onDone } = renderDialog(post, "reschedule", { onFailed });
    fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
      target: { value: FUTURE },
    });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Reschedule" }),
    );
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(text);
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  },
);

it("onFailed is not called after a success", async () => {
  const post = api.addPublication({
    content_id: media.id,
    account_id: youtube.id,
    status: "failed",
  });
  const onFailed = vi.fn();
  const { dialog, onDone } = renderDialog(post, "reschedule", { onFailed });
  fireEvent.change(within(dialog).getByLabelText(/Date and time/), {
    target: { value: FUTURE },
  });
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Reschedule" }),
  );
  await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  expect(onFailed).not.toHaveBeenCalled();
});
