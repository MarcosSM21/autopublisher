import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { renderRoute } from "../../test-utils.tsx";
import type { Content, Project } from "../../types.ts";

let api: FakeApi;
let project: Project;
let media: Content;

const FUTURE = "2099-06-01T10:00:00Z";

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
  media = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    title: "Clip",
    description: "Old caption",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function account(
  platform: "youtube" | "instagram" | "tiktok" | "threads",
  handle: string,
) {
  return api.addAccount({ project_id: project.id, platform, handle });
}

async function edit() {
  const user = userEvent.setup();
  renderRoute(`/p/${project.id}/library/${media.id}`);
  // Wait for the usage rows, which the warning is computed from.
  await screen.findByRole("heading", { name: "Usage" });
  await vi.waitFor(() =>
    expect(
      screen.getAllByRole("heading", { name: /Drafts|Upcoming|Published/ }),
    ).not.toHaveLength(0),
  );
  await user.click(screen.getByRole("button", { name: "Edit" }));
  return { user, form: screen.getByRole("form", { name: "Edit content" }) };
}

function patches() {
  return api.requests.filter((request) => request.method === "PATCH");
}

describe("Media content editing", () => {
  it("warns about the inheriting Posts only, never snapshots or published ones", async () => {
    api.addPublication({
      content_id: media.id,
      account_id: account("youtube", "chan").id,
    });
    api.addPublication({
      content_id: media.id,
      account_id: account("instagram", "l4i4").id,
      scheduled_at: FUTURE,
    });
    // A 019 draft carries its own text: not affected.
    api.addPublication({
      content_id: media.id,
      account_id: account("threads", "l4i4").id,
      description_override: "Own text",
      hashtags_override: [],
      title_override: "",
    });
    api.addPublication({
      content_id: media.id,
      account_id: account("tiktok", "cyber").id,
      status: "published",
      published_at: "2026-10-01T10:00:00Z",
    });
    const { user, form } = await edit();

    const caption = within(form).getByLabelText("Caption");
    await user.clear(caption);
    await user.type(caption, "New caption");

    const warning = within(form).getByRole("status");
    expect(warning).toHaveTextContent(
      "This change also updates 2 posts that use the media's text:",
    );
    expect(warning).toHaveTextContent("YouTube · chan · Draft");
    expect(warning).toHaveTextContent("Instagram · l4i4 · Scheduled · manual");
    expect(warning).not.toHaveTextContent("Threads");
    expect(warning).not.toHaveTextContent("TikTok");

    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(patches().map((request) => request.body)).toEqual([
      { description: "New caption" },
    ]);
    expect(await screen.findByText("New caption")).toBeInTheDocument();
  });

  describe("an automatic TikTok post whose declaration covers the caption", () => {
    beforeEach(() => {
      const post = api.addPublication({
        content_id: media.id,
        account_id: account("tiktok", "cyber").id,
        scheduled_at: FUTURE,
        auto_publish_enabled: true,
      });
      api.tiktokConsents.set(post.id, {
        fingerprint: "fp",
        version: "v1",
        consented_at: "2026-10-05T10:00:00Z",
      });
    });

    it("saves a title change without asking", async () => {
      const { user, form } = await edit();
      await user.type(within(form).getByLabelText("Title"), " v2");
      await user.click(within(form).getByRole("button", { name: "Save" }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      await vi.waitFor(() =>
        expect(patches().map((request) => request.body)).toEqual([
          { title: "Clip v2" },
        ]),
      );
    });

    it("asks before changing its caption; Cancel saves nothing", async () => {
      const { user, form } = await edit();
      await user.type(within(form).getByLabelText("Hashtags"), "#new");
      await user.click(within(form).getByRole("button", { name: "Save" }));

      const dialog = await screen.findByRole("dialog", {
        name: "Change the caption of scheduled TikTok posts?",
      });
      expect(dialog).toHaveTextContent(
        "TikTok won't publish these posts automatically until you confirm the TikTok declaration again.",
      );
      expect(dialog).toHaveTextContent("TikTok · cyber");
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(patches()).toHaveLength(0);
      expect(within(form).getByLabelText("Hashtags")).toHaveValue("#new");

      await user.click(within(form).getByRole("button", { name: "Save" }));
      await user.click(
        within(await screen.findByRole("dialog")).getByRole("button", {
          name: "Save anyway",
        }),
      );
      await vi.waitFor(() =>
        expect(patches().map((request) => request.body)).toEqual([
          { hashtags: ["new"] },
        ]),
      );
    });
  });

  it("shows field errors and keeps what was typed", async () => {
    api.addPublication({
      content_id: media.id,
      account_id: account("youtube", "chan").id,
    });
    const { user, form } = await edit();
    api.failNext(422, {
      error: {
        code: "validation_error",
        message: "The request contains invalid data.",
        fields: [
          {
            field: "hashtags",
            message: "Hashtags cannot be empty or contain spaces.",
          },
        ],
      },
    });
    await user.type(within(form).getByLabelText("Hashtags"), "#ok");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(
      await within(form).findByText(
        "Hashtags cannot be empty or contain spaces.",
      ),
    ).toBeInTheDocument();
    expect(within(form).getByLabelText("Hashtags")).toHaveValue("#ok");
    expect(within(form).getByLabelText("Hashtags")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});
