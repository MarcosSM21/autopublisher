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
import type { Account, Content, Project, Publication } from "../types.ts";
import ThreadsPublishOptions from "./ThreadsPublishOptions.tsx";

let api: FakeApi;
let project: Project;
let threads: Account;
let image: Content;
let video: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  threads = api.addAccount({
    project_id: project.id,
    platform: "threads",
    handle: "cyberstudio",
  });
  image = api.addContent({
    project_id: project.id,
    media_type: "image",
    media_format: "png",
    title: "Not sent",
    description: "Summer drop.",
    hashtags: ["cyber"],
  });
  video = api.addContent({
    project_id: project.id,
    media_type: "video",
    media_format: "mp4",
    description: "Clip",
    hashtags: [],
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function textPost(text: string, hashtags: string[] = []): Publication {
  return api.addPublication({
    content_id: null,
    account_id: threads.id,
    description_override: text,
    hashtags_override: hashtags,
  });
}

function renderOptions(publication: Publication) {
  const onSaved = vi.fn();
  render(<ThreadsPublishOptions publication={publication} onSaved={onSaved} />);
  return { user: userEvent.setup(), onSaved };
}

function puts() {
  return api.requests.filter(
    (request) =>
      request.method === "PUT" && request.path.endsWith("/threads-options"),
  );
}

describe("Threads options", () => {
  it("shows the exact text, preserving spaces and line breaks", async () => {
    renderOptions(
      textPost("  Line one\nline  two 🚀 https://a.example", ["cyber"]),
    );

    const text = await screen.findByRole("region", { name: "Text" });
    const pre = text.querySelector("pre")!;
    expect(pre.textContent).toBe(
      "  Line one\nline  two 🚀 https://a.example\n\n#cyber",
    );
    expect(within(text).getByText(/\/500 characters/)).toHaveTextContent(
      "51/500 characters (emoji count as several) · 1/5 links",
    );
    expect(
      within(text).getByText(/first link as a preview/),
    ).toBeInTheDocument();
    expect(within(text).getByText(/topic tag/)).toBeInTheDocument();
  });

  it("lists the problems of an invalid text and never shortens it", async () => {
    const long = "x".repeat(501);
    renderOptions(textPost(long));

    const problems = await screen.findByRole("list", {
      name: "Threads problems",
    });
    expect(problems).toHaveTextContent("Threads accepts at most 500.");
    expect(screen.getByRole("region", { name: "Text" })).toHaveTextContent(
      long,
    );
  });

  it("has no alt text nor media delivery notice for text posts", async () => {
    renderOptions(textPost("Hello"));

    await screen.findByText("Text post");
    expect(screen.queryByLabelText(/screen readers/)).not.toBeInTheDocument();
    expect(screen.queryByText(/temporary/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save Threads options" }),
    ).not.toBeInTheDocument();
  });

  it("saves the alt text of an image", async () => {
    const publication = api.addPublication({
      content_id: image.id,
      account_id: threads.id,
    });
    const { user, onSaved } = renderOptions(publication);

    await user.type(
      await screen.findByLabelText(/screen readers/),
      "A red square",
    );
    await user.click(
      screen.getByRole("button", { name: "Save Threads options" }),
    );

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(puts()[0].body).toEqual({ alt_text: "A red square" });
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    expect(screen.getByText(/temporary private storage/)).toBeInTheDocument();
  });

  it("offers alt text for videos too", async () => {
    renderOptions(
      api.addPublication({ content_id: video.id, account_id: threads.id }),
    );

    expect(await screen.findByText("Video")).toBeInTheDocument();
    expect(screen.getByLabelText(/screen readers/)).toBeInTheDocument();
  });

  it("shows the alt text limit error", async () => {
    const { user } = renderOptions(
      api.addPublication({ content_id: image.id, account_id: threads.id }),
    );

    const field = await screen.findByLabelText(/screen readers/);
    await user.click(field);
    await user.paste("a".repeat(1001));
    await user.click(
      screen.getByRole("button", { name: "Save Threads options" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The alt text can have at most 1000 characters.",
    );
  });

  it("is read-only when the publication cannot be edited", async () => {
    renderOptions(
      api.addPublication({
        content_id: image.id,
        account_id: threads.id,
        status: "published",
        published_at: "2026-10-05T11:00:00Z",
      }),
    );

    expect(await screen.findByLabelText(/screen readers/)).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Save Threads options" }),
    ).not.toBeInTheDocument();
  });

  it("warns when media delivery is not configured", async () => {
    api.threadsDeliveryConfigured = false;
    renderOptions(
      api.addPublication({ content_id: image.id, account_id: threads.id }),
    );

    expect(
      await screen.findByText(/media delivery is not configured: images/),
    ).toBeInTheDocument();
  });
});
