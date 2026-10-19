import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
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
  });
  const account = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "chan",
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

function answer(legend: string, value: "Yes" | "No") {
  return within(screen.getByRole("group", { name: legend })).getByRole(
    "radio",
    { name: value },
  );
}

describe("YouTube details", () => {
  it("saves each choice on change and becomes Ready", async () => {
    const { user } = renderCard(publication);
    const region = card(/YouTube/);

    expect(
      await within(region).findByText(
        "YouTube needs 2 details: Made for kids and Altered or synthetic content.",
      ),
    ).toBeInTheDocument();
    expect(within(region).getByText("Details needed")).toBeInTheDocument();

    await user.click(answer("Made for kids?", "No"));
    expect(await within(region).findByText("Saved")).toBeInTheDocument();
    expect(writes(api).at(-1)).toEqual({
      method: "PUT",
      path: `/publications/${publication.id}/youtube-options`,
      body: {
        privacy_status: "private",
        made_for_kids: false,
        contains_synthetic_media: null,
        notify_subscribers: false,
      },
    });

    await user.click(answer("Altered or synthetic content?", "No"));
    expect(await within(region).findByText("Ready")).toBeInTheDocument();
    // No Save button: every change saves on its own.
    expect(
      within(region).queryByRole("button", { name: /Save/ }),
    ).not.toBeInTheDocument();
    // Still open: a save never folds the card away under the user.
    expect(answer("Made for kids?", "No")).toBeVisible();
  });

  it("shows a failed save with Retry, which sends the last value again", async () => {
    const { user } = renderCard(publication);
    const region = card(/YouTube/);
    await within(region).findByText("Details needed");

    api.failNext(500, {
      error: { code: "server_error", message: "Try again.", fields: [] },
    });
    await user.click(answer("Made for kids?", "Yes"));
    expect(
      await within(region).findByText("Couldn't save: Try again."),
    ).toBeInTheDocument();

    await user.click(within(region).getByRole("button", { name: "Retry" }));
    expect(await within(region).findByText("Saved")).toBeInTheDocument();
    const puts = writes(api).filter((request) => request.method === "PUT");
    expect(puts).toHaveLength(2);
    expect(puts[1].body).toEqual(puts[0].body);
  });
});
