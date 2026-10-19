import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi, TT_CREATOR_INFO } from "../../test-fake-api.ts";
import type { Publication } from "../../types.ts";
import { card, renderCard, writes } from "./test-card.tsx";

let api: FakeApi;
let publication: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  const project = api.addProject({ name: "Cyber" });
  const video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    description: "Clip",
  });
  const account = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyber",
  });
  publication = api.addPublication({
    content_id: video.id,
    account_id: account.id,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function modes() {
  return screen.getByRole("group", { name: "How should this reach TikTok?" });
}

function noMode() {
  api.tiktokOptions.set(publication.id, {
    mode: null,
    privacy_level: null,
    allow_comment: false,
    allow_duet: false,
    allow_stitch: false,
    commercial_disclosure_enabled: false,
    brand_organic_toggle: false,
    brand_content_toggle: false,
    is_aigc: null,
  });
}

describe("TikTok details", () => {
  it("asks first how the video reaches TikTok and saves the choice", async () => {
    noMode();
    const { user } = renderCard(publication);
    const region = card(/TikTok/);
    await within(region).findByText(
      "TikTok needs 1 detail: How to reach TikTok.",
    );

    await user.click(
      within(modes()).getByRole("radio", { name: "Send to my TikTok inbox" }),
    );
    expect(
      await within(region).findByText(
        "You'll get a TikTok inbox notification to finish the post.",
      ),
    ).toBeInTheDocument();
    expect(await within(region).findByText("Ready")).toBeInTheDocument();
    expect(writes(api).at(-1)).toMatchObject({
      method: "PUT",
      body: { mode: "INBOX_UPLOAD" },
    });
  });

  it("shows an unavailable mode with its reason", async () => {
    noMode();
    api.tiktokInboxAvailable = false;
    renderCard(publication);
    await screen.findByRole("group", { name: "How should this reach TikTok?" });

    expect(
      within(modes()).getByRole("radio", { name: /Send to my TikTok inbox/ }),
    ).toBeDisabled();
    expect(
      within(modes()).getByText(/needs the video.upload permission/),
    ).toBeInTheDocument();
  });

  it("offers Retry and Send to inbox instead when Creator Info fails", async () => {
    api.tiktokCreatorInfo = {
      status: 502,
      code: "tiktok_unavailable",
      message: "TikTok did not answer.",
    };
    const { user } = renderCard(publication);
    const region = card(/TikTok/);

    expect(
      await within(region).findByText("TikTok did not answer."),
    ).toBeVisible();
    api.tiktokCreatorInfo = TT_CREATOR_INFO;
    await user.click(within(region).getByRole("button", { name: "Retry" }));
    expect(await within(region).findByText("Cyber Studio")).toBeInTheDocument();

    api.tiktokCreatorInfo = {
      status: 502,
      code: "tiktok_unavailable",
      message: "TikTok did not answer.",
    };
    cleanup();
    const second = renderCard(publication);
    const again = card(/TikTok/);
    await second.user.click(
      await within(again).findByRole("button", {
        name: "Send to inbox instead",
      }),
    );
    expect(
      await within(again).findByText(
        "You'll get a TikTok inbox notification to finish the post.",
      ),
    ).toBeInTheDocument();
    expect(writes(api).at(-1)).toMatchObject({
      body: { mode: "INBOX_UPLOAD" },
    });
  });

  it("says clearly when TikTok only allows private posts, and never records the declaration", async () => {
    const { user } = renderCard(publication);
    const region = card(/TikTok/);

    const privacy = await within(region).findByRole("group", {
      name: "Who can view this video?",
    });
    // Only what TikTok allows, nothing preselected.
    expect(
      within(privacy)
        .getAllByRole("radio")
        .map((radio) => radio.closest("label")?.textContent),
    ).toEqual(["Only me"]);
    expect(within(privacy).getByRole("radio")).not.toBeChecked();
    expect(
      within(region).getByText(
        "This TikTok app can only post privately: only you will see the video.",
      ),
    ).toBeInTheDocument();
    expect(
      within(region).getByText(
        "TikTok needs 2 details: Privacy and AI-generated content.",
      ),
    ).toBeInTheDocument();

    await user.click(within(privacy).getByRole("radio", { name: "Only me" }));
    await user.click(
      within(
        within(region).getByRole("group", { name: "AI-generated content?" }),
      ).getByRole("radio", { name: "No" }),
    );
    const declaration = await within(region).findByRole("checkbox", {
      name: /I agree to the declaration/,
    });
    await vi.waitFor(() => expect(declaration).toBeEnabled());
    // Complete options: the backend now asks for the declaration.
    expect(
      await within(region).findByText("TikTok needs 1 detail: declaration."),
    ).toBeInTheDocument();
    await user.click(declaration);

    expect(declaration).toBeChecked();
    expect(await within(region).findByText("Ready")).toBeInTheDocument();
    // Interactions stay off unless chosen.
    expect(writes(api).at(-1)?.body).toMatchObject({
      allow_comment: false,
      allow_duet: false,
      allow_stitch: false,
    });
    expect(
      api.requests.filter((request) =>
        request.path.endsWith("/tiktok-consent"),
      ),
    ).toHaveLength(0);
    // A single declaration in the card.
    expect(
      within(region).getAllByRole("checkbox", { name: /declaration/ }),
    ).toHaveLength(1);
  });
});
