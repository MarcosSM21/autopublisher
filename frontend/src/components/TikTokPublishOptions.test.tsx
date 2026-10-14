import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi, TT_CREATOR_INFO } from "../test-fake-api.ts";
import type {
  Account,
  Content,
  Project,
  Publication,
  TikTokPublicationOptionsWrite,
} from "../types.ts";
import TikTokPublishOptions from "./TikTokPublishOptions.tsx";

let api: FakeApi;
let project: Project;
let tiktok: Account;
let video: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  tiktok = api.addAccount({
    project_id: project.id,
    platform: "tiktok",
    handle: "cyberstudio",
  });
  video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    title: "Not sent",
    description: "Summer drop 😀",
    hashtags: ["cyber"],
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function publication(): Publication {
  return api.addPublication({ content_id: video.id, account_id: tiktok.id });
}

function renderOptions(target: Publication = publication()) {
  const onSaved = vi.fn();
  render(<TikTokPublishOptions publication={target} onSaved={onSaved} />);
  return { user: userEvent.setup(), onSaved, publication: target };
}

function requestsTo(suffix: string, method = "GET") {
  return api.requests.filter(
    (request) => request.method === method && request.path.endsWith(suffix),
  );
}

describe("TikTok review", () => {
  it("shows who receives the post from Creator Info", async () => {
    renderOptions();

    const creator = await screen.findByRole("region", {
      name: "TikTok account",
    });
    expect(within(creator).getByText(/Cyber Studio/)).toBeInTheDocument();
    expect(within(creator).getByText(/@cyber\.studio/)).toBeInTheDocument();
    expect(
      within(creator).getByRole("img", { name: "TikTok avatar" }),
    ).toHaveAttribute("src", TT_CREATOR_INFO.avatar_url);
    expect(requestsTo("/tiktok-creator-info")).toHaveLength(1);
  });

  it("previews the video that will be sent", async () => {
    renderOptions();

    const region = await screen.findByRole("region", { name: "Video" });
    const preview = region.querySelector("video")!;
    expect(preview).toHaveAttribute("src", video.file_url);
    expect(preview).toHaveAttribute("controls");
  });

  it("shows the exact caption and its TikTok count", async () => {
    renderOptions();

    const caption = await screen.findByRole("region", { name: "Caption" });
    expect(caption.querySelector("pre")!.textContent).toBe(
      "Summer drop 😀\n\n#cyber",
    );
    // "😀" counts 2 (UTF-16 code units).
    expect(within(caption).getByText("22/2200")).toBeInTheDocument();
  });

  it("has no preselected privacy and only Only me is enabled", async () => {
    renderOptions();

    const select = (await screen.findByLabelText(
      "Who can view this video",
    )) as HTMLSelectElement;
    expect(select.value).toBe("");
    const options = within(select).getAllByRole(
      "option",
    ) as HTMLOptionElement[];
    const byValue = Object.fromEntries(options.map((o) => [o.value, o]));
    expect(Object.keys(byValue)).toEqual([
      "",
      "FOLLOWER_OF_CREATOR",
      "MUTUAL_FOLLOW_FRIENDS",
      "SELF_ONLY",
    ]);
    expect(byValue.SELF_ONLY.disabled).toBe(false);
    expect(byValue.FOLLOWER_OF_CREATOR.disabled).toBe(true);
    expect(byValue.MUTUAL_FOLLOW_FRIENDS.disabled).toBe(true);
    expect(
      screen.getAllByText(/This TikTok app is not audited/).length,
    ).toBeGreaterThan(0);
  });

  it("starts with interactions unchecked and greys the disabled ones", async () => {
    renderOptions();

    const comments = await screen.findByLabelText("Allow comments");
    const duet = screen.getByLabelText("Allow duet");
    const stitch = screen.getByLabelText("Allow stitch");
    expect(comments).not.toBeChecked();
    expect(comments).toBeEnabled();
    expect(duet).not.toBeChecked();
    expect(duet).toBeDisabled();
    expect(stitch).not.toBeChecked();
    expect(stitch).toBeDisabled();
    expect(
      screen.getAllByText(/turned off in this TikTok account/).length,
    ).toBe(2);
  });

  it("asks for an explicit AI-generated answer and shows the disclosure off", async () => {
    renderOptions();

    const group = await screen.findByRole("radiogroup", {
      name: "AI-generated",
    });
    for (const radio of within(group).getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
    expect(
      screen.getByLabelText("Disclose commercial content"),
    ).not.toBeChecked();
  });

  it("saves every choice and records the consent for the current fingerprint", async () => {
    const { user, onSaved, publication: target } = renderOptions();

    await user.selectOptions(
      await screen.findByLabelText("Who can view this video"),
      "SELF_ONLY",
    );
    await user.click(screen.getByLabelText("Allow comments"));
    const group = screen.getByRole("radiogroup", { name: "AI-generated" });
    await user.click(within(group).getByLabelText("No"));

    const declaration = screen.getByRole("region", { name: "Declaration" });
    expect(declaration).toHaveTextContent(
      "By posting, you agree to TikTok's Music Usage Confirmation.",
    );
    expect(
      within(declaration).getByRole("link", {
        name: "Music Usage Confirmation",
      }),
    ).toHaveAttribute(
      "href",
      "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en",
    );
    const puts = requestsTo("/tiktok-options", "PUT");
    expect(puts.at(-1)!.body).toEqual({
      privacy_level: "SELF_ONLY",
      allow_comment: true,
      allow_duet: false,
      allow_stitch: false,
      commercial_disclosure_enabled: false,
      brand_organic_toggle: false,
      brand_content_toggle: false,
      is_aigc: false,
    });

    const fingerprint = api.tiktokOptionsView(
      api.publications.find((p) => p.id === target.id)!,
    ).fingerprint;
    await user.click(
      within(declaration).getByLabelText(/I agree to the declaration above/),
    );

    await waitFor(() =>
      expect(requestsTo("/tiktok-consent", "POST")).toHaveLength(1),
    );
    expect(requestsTo("/tiktok-consent", "POST")[0].body).toEqual({
      fingerprint,
      declaration_version: "music-usage-2026-10-14",
    });
    expect(
      await within(declaration).findByText(
        "Consent recorded — matches saved publication metadata",
      ),
    ).toBeInTheDocument();
    expect(
      within(declaration).getByText(
        "File integrity is rechecked before publishing.",
      ),
    ).toBeInTheDocument();
    expect(declaration).not.toHaveTextContent(/verified/i);
    expect(onSaved).toHaveBeenCalled();
  });

  it("cannot confirm the declaration while options are incomplete", async () => {
    renderOptions();

    const declaration = await screen.findByRole("region", {
      name: "Declaration",
    });
    expect(
      within(declaration).getByLabelText(/I agree to the declaration above/),
    ).toBeDisabled();
  });

  it("refreshes Creator Info on demand", async () => {
    const { user } = renderOptions();

    await screen.findByText(/Cyber Studio/);
    api.tiktokCreatorInfo = { ...TT_CREATOR_INFO, nickname: "Renamed Studio" };
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText(/Renamed Studio/)).toBeInTheDocument();
    expect(requestsTo("/tiktok-creator-info")).toHaveLength(2);
  });

  it("explains when the creator cannot post", async () => {
    api.tiktokCreatorInfo = {
      ...TT_CREATOR_INFO,
      nickname: null,
      username: null,
      avatar_url: null,
      privacy_level_options: null,
      comment_disabled: null,
      duet_disabled: null,
      stitch_disabled: null,
      max_video_post_duration_sec: null,
      can_post: false,
      blocked: {
        code: "tiktok_creator_cannot_post",
        message:
          "This TikTok account reached its daily posting limit. Try again later.",
      },
      video_within_max_duration: null,
    };
    renderOptions();

    expect(
      await screen.findByText(/reached its daily posting limit/),
    ).toBeInTheDocument();
  });

  it("shows a Creator Info error without breaking the review", async () => {
    api.tiktokCreatorInfo = {
      status: 503,
      code: "tiktok_unavailable",
      message:
        "Could not reach TikTok. Nothing was published. Try again later.",
    };
    renderOptions();

    expect(
      await screen.findByText(/Could not reach TikTok/),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("region", { name: "Caption" }),
    ).toBeInTheDocument();
  });
});

describe("complete TikTok review", () => {
  const SAVED: TikTokPublicationOptionsWrite = {
    privacy_level: "SELF_ONLY",
    allow_comment: false,
    allow_duet: false,
    allow_stitch: false,
    commercial_disclosure_enabled: false,
    brand_organic_toggle: false,
    brand_content_toggle: false,
    is_aigc: false,
  };

  function saved(values: Partial<typeof SAVED> = {}, extra = {}): Publication {
    const target = api.addPublication({
      content_id: video.id,
      account_id: tiktok.id,
      ...extra,
    });
    api.tiktokOptions.set(target.id, { ...SAVED, ...values });
    return target;
  }

  function consent(target: Publication) {
    const record = api.publications.find((p) => p.id === target.id)!;
    const view = api.tiktokOptionsView(record);
    api.tiktokConsents.set(target.id, {
      fingerprint: view.fingerprint!,
      version: view.declaration.version,
      consented_at: "2026-10-05T10:30:00Z",
    });
  }

  it("reveals Your brand and Branded content when the disclosure is on", async () => {
    const { user } = renderOptions(saved());

    expect(screen.queryByLabelText("Your brand")).not.toBeInTheDocument();
    await user.click(
      await screen.findByLabelText("Disclose commercial content"),
    );

    expect(await screen.findByLabelText("Your brand")).toBeInTheDocument();
    expect(screen.getByLabelText("Branded content")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "You need to indicate if your content promotes yourself, a third party, or both.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("labels Your brand as promotional content", async () => {
    const { user } = renderOptions(
      saved({ commercial_disclosure_enabled: true }),
    );

    await user.click(await screen.findByLabelText("Your brand"));

    expect(
      await screen.findByText(
        "Your video will be labeled as 'Promotional content'",
      ),
    ).toBeInTheDocument();
    expect(requestsTo("/tiktok-options", "PUT").at(-1)!.body).toMatchObject({
      commercial_disclosure_enabled: true,
      brand_organic_toggle: true,
      brand_content_toggle: false,
    });
  });

  it("blocks Branded content while the video is private and explains why", async () => {
    renderOptions(saved({ commercial_disclosure_enabled: true }));

    const branded = await screen.findByLabelText("Branded content");
    expect(branded).toBeDisabled();
    expect(
      screen.getByText(/Branded content visibility cannot be set to private\./),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/this TikTok app is not audited/i, {
        selector: ".branded-reason",
      }),
    ).toBeInTheDocument();
  });

  it("switches the declaration and label with Branded content", async () => {
    renderOptions(
      saved({
        privacy_level: "FOLLOWER_OF_CREATOR",
        commercial_disclosure_enabled: true,
        brand_content_toggle: true,
      }),
    );

    const declaration = await screen.findByRole("region", {
      name: "Declaration",
    });
    expect(declaration).toHaveTextContent(
      "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation.",
    );
    expect(
      within(declaration).getByRole("link", { name: "Branded Content Policy" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Your video will be labeled as 'Paid partnership'"),
    ).toBeInTheDocument();
  });

  it("asks to confirm again after a material change", async () => {
    const target = saved();
    consent(target);
    api.publications.find((p) => p.id === target.id)!.description_override =
      "Edited after consenting";
    renderOptions(
      api.publicationView(api.publications.find((p) => p.id === target.id)!),
    );

    const declaration = await screen.findByRole("region", {
      name: "Declaration",
    });
    expect(declaration).toHaveTextContent(/confirm again/i);
    const checkbox = within(declaration).getByLabelText(
      /I agree to the declaration above/,
    );
    expect(checkbox).not.toBeChecked();
    expect(checkbox).toBeEnabled();
  });

  it("warns an armed publication with a stale consent", async () => {
    const target = saved(
      {},
      {
        scheduled_at: "2100-01-01T10:00:00Z",
        status: "scheduled",
        auto_publish_enabled: true,
      },
    );
    consent(target);
    api.publications.find((p) => p.id === target.id)!.description_override =
      "Edited";
    renderOptions(
      api.publicationView(api.publications.find((p) => p.id === target.id)!),
    );

    expect(
      await screen.findByText(
        /will not be published automatically until you confirm the declaration again/,
      ),
    ).toBeInTheDocument();
  });

  it("warns when the TikTok account appears public", async () => {
    api.tiktokCreatorInfo = {
      ...TT_CREATOR_INFO,
      privacy_level_options: [
        "PUBLIC_TO_EVERYONE",
        "MUTUAL_FOLLOW_FRIENDS",
        "SELF_ONLY",
      ],
      account_appears_public: true,
    };
    renderOptions(saved());

    expect(
      await screen.findByText(/appears to be public; set it to private/),
    ).toBeInTheDocument();
  });

  it("shows that the file no longer matches the confirmed video", async () => {
    const target = saved();
    api.tiktokIntegrityWarnings.set(target.id, {
      code: "tiktok_video_changed",
      message:
        "The video file no longer matches the one you confirmed. Nothing was sent to TikTok.",
      at: "2026-10-05T11:00:00Z",
    });
    renderOptions(target);

    expect(
      await screen.findByText(/no longer matches the one you confirmed/),
    ).toBeInTheDocument();
  });

  it("never claims the current bytes were verified", async () => {
    const target = saved();
    consent(target);
    renderOptions(target);

    const declaration = await screen.findByRole("region", {
      name: "Declaration",
    });
    expect(declaration).toHaveTextContent(
      "Consent recorded — matches saved publication metadata",
    );
    expect(declaration).toHaveTextContent(
      "File integrity is rechecked before publishing.",
    );
    expect(declaration).not.toHaveTextContent(/verified/i);
  });

  it("says TikTok may take a few minutes to process", async () => {
    renderOptions(saved());

    expect(
      await screen.findByText(
        /TikTok may take a few minutes to process the video/,
      ),
    ).toBeInTheDocument();
  });
});
