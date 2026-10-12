import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Project, Publication } from "../types.ts";
import InstagramPublishOptions from "./InstagramPublishOptions.tsx";

let api: FakeApi;
let project: Project;
let image: Content;
let video: Content;
let instagram: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  image = api.addContent({
    project_id: project.id,
    media_type: "image",
    media_format: "png",
    title: "Not sent",
    description: "Summer drop.",
    hashtags: ["cyber", "studio"],
  });
  video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    description: "Reel time",
    hashtags: [],
  });
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "cyberstudio",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function add(content: Content): Publication {
  return api.addPublication({
    content_id: content.id,
    account_id: instagram.id,
  });
}

function renderOptions(publication: Publication) {
  const onSaved = vi.fn();
  render(
    <InstagramPublishOptions publication={publication} onSaved={onSaved} />,
  );
  return { user: userEvent.setup(), onSaved };
}

function puts() {
  return api.requests.filter(
    (request) =>
      request.method === "PUT" && request.path.endsWith("/instagram-options"),
  );
}

describe("image post", () => {
  it("shows the exact caption and requires the AI declaration", async () => {
    renderOptions(add(image));

    expect(await screen.findByText("Image Post")).toBeInTheDocument();
    const caption = screen.getByRole("region", { name: "Caption" });
    expect(caption.querySelector("pre")?.textContent).toBe(
      "Summer drop.\n\n#cyber #studio",
    );
    expect(caption).toHaveTextContent("2/30 hashtags");
    expect(caption).toHaveTextContent("The title is not sent to Instagram.");
    expect(screen.queryByText("Not sent")).not.toBeInTheDocument();
    expect(screen.getByText("Not declared")).toBeInTheDocument();
    expect(
      screen.getByText("Declare whether the content is AI-generated."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Share to feed")).not.toBeInTheDocument();
  });

  it("saves the AI declaration and the alt text", async () => {
    const publication = add(image);
    const { user, onSaved } = renderOptions(publication);
    await screen.findByText("Image Post");

    const ai = screen.getByRole("group", { name: "AI-generated content" });
    await user.click(
      ai.querySelector('input[type="radio"]') as HTMLInputElement,
    );
    await user.type(
      screen.getByLabelText(/Describes the image/),
      "A neon sign",
    );
    expect(screen.getByText("11/1000")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Save Instagram options" }),
    );

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalledOnce();
    expect(puts()[0].body).toEqual({
      is_ai_generated: true,
      alt_text: "A neon sign",
    });
    expect(api.instagramOptions.get(publication.id)?.alt_text).toBe(
      "A neon sign",
    );
  });

  it("lists problems such as missing media delivery", async () => {
    api.instagramDeliveryConfigured = false;

    renderOptions(add(image));

    expect(
      await screen.findByText("Temporary media delivery is not configured."),
    ).toBeInTheDocument();
  });
});

describe("reel", () => {
  it("offers share to feed (on by default) and no alt text", async () => {
    const publication = add(video);
    const { user } = renderOptions(publication);

    expect(await screen.findByText("Reel")).toBeInTheDocument();
    const share = screen.getByRole("checkbox");
    expect(share).toBeChecked();
    expect(screen.queryByText("Alt text")).not.toBeInTheDocument();

    const ai = screen.getByRole("group", { name: "AI-generated content" });
    const no = ai.querySelectorAll(
      'input[type="radio"]',
    )[1] as HTMLInputElement;
    await user.click(no);
    await user.click(share);
    await user.click(
      screen.getByRole("button", { name: "Save Instagram options" }),
    );

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      is_ai_generated: false,
      share_to_feed: false,
    });
  });
});

it("is read-only once published", async () => {
  const publication = add(image);
  Object.assign(
    api.publications.find((p) => p.id === publication.id)!,
    {
      status: "published",
    },
  );

  renderOptions(publication);

  await screen.findByText("Image Post");
  expect(
    screen.queryByRole("button", { name: "Save Instagram options" }),
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText(/Describes the image/)).toBeDisabled();
});
