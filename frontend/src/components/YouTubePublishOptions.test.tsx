import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Publication } from "../types.ts";
import PublicationDetail from "./PublicationDetail.tsx";
import YouTubePublishOptions from "./YouTubePublishOptions.tsx";

let api: FakeApi;
let video: Content;
let youtube: Account;
let publication: Publication;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  const project = api.addProject({ name: "Cyber" });
  video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    title: "Cybersecurity basics",
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "cyberchannel",
  });
  publication = api.addPublication({
    content_id: video.id,
    account_id: youtube.id,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function group(name: string) {
  return screen.getByRole("group", { name });
}

async function renderOptions(onSaved = vi.fn()) {
  render(<YouTubePublishOptions publication={publication} onSaved={onSaved} />);
  await screen.findByRole("form", { name: "YouTube options" });
  return { user: userEvent.setup(), onSaved };
}

describe("YouTube options", () => {
  it("shows the safe defaults and leaves declarations undecided", async () => {
    await renderOptions();

    expect(
      within(group("Privacy")).getByRole("radio", { name: "Private" }),
    ).toBeChecked();
    expect(
      within(group("Notify subscribers")).getByRole("radio", { name: "No" }),
    ).toBeChecked();
    for (const name of ["Made for kids", "Altered or synthetic content"]) {
      for (const radio of within(group(name)).getAllByRole("radio")) {
        expect(radio).not.toBeChecked();
      }
      expect(within(group(name)).getByText("Not declared")).toBeInTheDocument();
    }
    expect(
      screen.getByText(
        "YouTube may restrict videos uploaded from unverified API projects to private.",
      ),
    ).toBeInTheDocument();
  });

  it("saves the four options", async () => {
    const { user, onSaved } = await renderOptions();

    await user.click(
      within(group("Privacy")).getByRole("radio", { name: "Unlisted" }),
    );
    await user.click(
      within(group("Made for kids")).getByRole("radio", { name: "No" }),
    );
    await user.click(
      within(group("Altered or synthetic content")).getByRole("radio", {
        name: "Yes",
      }),
    );
    await user.click(
      within(group("Notify subscribers")).getByRole("radio", { name: "Yes" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save YouTube options" }),
    );

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const put = api.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({
      privacy_status: "unlisted",
      made_for_kids: false,
      contains_synthetic_media: true,
      notify_subscribers: true,
    });
  });

  it("is read-only when the publication can no longer change", async () => {
    api.youtubeOptions.set(publication.id, {
      privacy_status: "private",
      made_for_kids: false,
      contains_synthetic_media: false,
      notify_subscribers: false,
    });
    api.publications.find((p) => p.id === publication.id)!.status = "published";

    await renderOptions();

    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toBeDisabled();
    }
    expect(
      screen.queryByRole("button", { name: "Save YouTube options" }),
    ).not.toBeInTheDocument();
  });

  it("is not shown for other platforms", async () => {
    const instagram = api.addAccount({
      project_id: video.project_id,
      platform: "instagram",
      handle: "cyber",
    });
    const other = api.addPublication({
      content_id: video.id,
      account_id: instagram.id,
    });

    render(<PublicationDetail publication={other} onChanged={vi.fn()} />);

    await screen.findByRole("form", { name: "Metadata" });
    expect(
      screen.queryByRole("form", { name: "YouTube options" }),
    ).not.toBeInTheDocument();
    expect(
      api.requests.some((request) => request.path.includes("youtube-options")),
    ).toBe(false);
  });
});
