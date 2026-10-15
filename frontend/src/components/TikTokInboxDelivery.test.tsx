import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type {
  Account,
  Content,
  Publication,
  TikTokDeliveryState,
} from "../types.ts";
import TikTokInboxDelivery from "./TikTokInboxDelivery.tsx";

let api: FakeApi;
let tiktok: Account;
let video: Content;

const INBOX_OPTIONS = {
  mode: "INBOX_UPLOAD" as const,
  privacy_level: "SELF_ONLY" as const,
  allow_comment: true,
  allow_duet: false,
  allow_stitch: false,
  commercial_disclosure_enabled: false,
  brand_organic_toggle: false,
  brand_content_toggle: false,
  is_aigc: false,
};

beforeEach(() => {
  api = new FakeApi();
  api.install();
  const project = api.addProject({ name: "Cyber" });
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
    description: "Summer drop caption",
    hashtags: ["cyber"],
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function inboxPublication(status?: string): Publication {
  const publication = api.addPublication({
    content_id: video.id,
    account_id: tiktok.id,
  });
  // Direct Post options kept from before: never shown as the post's settings.
  api.tiktokOptions.set(publication.id, INBOX_OPTIONS);
  const record = api.publications.find((p) => p.id === publication.id)!;
  if (status === "awaiting_user_action") {
    api.startAttempt(record);
    api.deliverToInbox(publication.id);
  } else if (status) {
    Object.assign(record, { status });
  }
  return api.publicationView(record);
}

function renderDelivery(publication: Publication) {
  const onChanged = vi.fn();
  render(
    <TikTokInboxDelivery publication={publication} onChanged={onChanged} />,
  );
  return { user: userEvent.setup(), onChanged };
}

function checks() {
  return api.requests.filter((request) =>
    request.path.endsWith("/check-status"),
  );
}

describe("TikTok inbox delivery", () => {
  it.each<[string, TikTokDeliveryState, string]>([
    ["scheduled", "scheduled", "Scheduled"],
    ["publishing", "uploading", "Uploading"],
    ["publishing", "processing", "Processing in TikTok"],
    ["awaiting_user_action", "ready", "Ready in TikTok"],
    ["published", "published", "Published"],
    ["failed", "failed", "Failed"],
  ])(
    "shows %s as %s without any final post metadata",
    async (status, state, label) => {
      const publication = inboxPublication(status);
      api.tiktokDeliveries.set(publication.id, { state });
      renderDelivery(publication);

      const region = await screen.findByRole("region", {
        name: "TikTok delivery",
      });
      expect(region).toHaveTextContent(label);
      // Caption, privacy, sound, effects, hashtags, cover and the like are
      // chosen in TikTok: none is presented as known configuration.
      for (const text of [
        "Summer drop caption",
        "#cyber",
        "Only me",
        "Privacy",
        "Caption",
        "Sound",
        "Effects",
        "Hashtags",
        "Cover",
        "Comments",
      ]) {
        expect(region).not.toHaveTextContent(text);
      }
      if (state !== "ready") {
        expect(
          screen.queryByRole("button", { name: "Check status" }),
        ).toBeNull();
      }
    },
  );

  it("explains what to do when the video is in the inbox", async () => {
    renderDelivery(inboxPublication("awaiting_user_action"));

    const region = await screen.findByRole("region", {
      name: "TikTok delivery",
    });
    expect(region).toHaveTextContent(
      "Open your TikTok inbox to review, edit and publish the video.",
    );
    expect(region).toHaveTextContent(
      "TikTok inbox notification (not necessarily a phone push notification)",
    );
    expect(screen.getByRole("button", { name: "Check status" })).toBeEnabled();
  });

  it("shows nothing before sending or for Direct Post", async () => {
    renderDelivery(inboxPublication());
    await waitFor(() =>
      expect(
        api.requests.some((r) => r.path.endsWith("/tiktok-delivery")),
      ).toBe(true),
    );
    expect(
      screen.queryByRole("region", { name: "TikTok delivery" }),
    ).toBeNull();
  });

  it("keeps waiting and says so", async () => {
    const publication = inboxPublication("awaiting_user_action");
    const { user, onChanged } = renderDelivery(publication);

    await user.click(
      await screen.findByRole("button", { name: "Check status" }),
    );

    expect(
      await screen.findByText(
        "TikTok is still waiting for you to finish the post there.",
      ),
    ).toBeInTheDocument();
    expect(checks()).toHaveLength(1);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("reports the publication once the user published it in TikTok", async () => {
    const publication = inboxPublication("awaiting_user_action");
    api.checkStatusOutcomes.set(publication.id, {
      result: "published",
      message: "You published it in TikTok.",
    });
    const { user, onChanged } = renderDelivery(publication);

    await user.click(
      await screen.findByRole("button", { name: "Check status" }),
    );

    expect(
      await screen.findByText("You published it in TikTok."),
    ).toBeInTheDocument();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(onChanged.mock.calls[0][0].status).toBe("published");
  });

  it("disables Check status while the check is pending", async () => {
    const publication = inboxPublication("awaiting_user_action");
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const fetch = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: RequestInfo, init?: RequestInit) => {
      if (String(input).endsWith("/check-status")) {
        await gate;
      }
      return fetch(input, init);
    });
    const { user } = renderDelivery(publication);
    const button = await screen.findByRole("button", { name: "Check status" });

    await user.click(button);
    expect(
      await screen.findByRole("button", { name: "Checking…" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Checking…" }));
    release();

    expect(
      await screen.findByRole("button", { name: "Check status" }),
    ).toBeEnabled();
    expect(checks()).toHaveLength(1);
  });

  it("shows a check error without changing anything", async () => {
    const publication = inboxPublication("awaiting_user_action");
    api.checkStatusOutcomes.set(publication.id, {
      status: 503,
      body: {
        error: {
          code: "tiktok_unavailable",
          message:
            "Could not reach TikTok to check this video. Nothing changed; try again later.",
          fields: [],
        },
      },
    });
    const { user, onChanged } = renderDelivery(publication);

    await user.click(
      await screen.findByRole("button", { name: "Check status" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not reach TikTok to check this video.",
    );
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("shows a failure TikTok reported after the delivery", async () => {
    const publication = inboxPublication("failed");
    api.tiktokDeliveries.set(publication.id, {
      state: "failed",
      after_delivery_failure: {
        code: "tiktok_content_rejected",
        message: "TikTok rejected the content.",
      },
    });
    renderDelivery(publication);

    expect(
      await screen.findByText("TikTok rejected the content."),
    ).toBeInTheDocument();
  });
});
