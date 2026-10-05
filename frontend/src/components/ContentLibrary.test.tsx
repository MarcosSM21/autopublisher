import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Project } from "../types.ts";
import ProjectDetail from "./ProjectDetail.tsx";

let api: FakeApi;
let project: Project;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "L4i4" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function makeFile(name: string, size = 10): File {
  return new File(["x".repeat(size)], name);
}

/** Every test starts from the project detail and opens its content library. */
async function openLibrary(selected: Project = project) {
  // The backend validates formats; the picker filter is only a convenience.
  const user = userEvent.setup({ applyAccept: false });
  render(<ProjectDetail project={selected} onProjectChanged={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Content" }));
  return user;
}

function dropZone() {
  return screen.getByRole("region", { name: "Import files" });
}

function fileInput() {
  return screen.getByLabelText<HTMLInputElement>("Choose files");
}

function dropFiles(files: File[]) {
  const dataTransfer = { files, types: ["Files"] };
  fireEvent.dragOver(dropZone(), { dataTransfer });
  fireEvent.drop(dropZone(), { dataTransfer });
}

function importRequests() {
  return api.requests.filter(
    (request) =>
      request.method === "POST" && request.path.endsWith("/contents"),
  );
}

/** Waits until a whole import operation has finished. */
async function waitForImport() {
  await screen.findByText(/\d+ imported · /);
}

async function resultItems() {
  const list = await screen.findByRole("list", { name: "Import results" });
  return within(list).findAllByRole("listitem");
}

describe("Content import (US1)", () => {
  it("opens the content view from the project detail", async () => {
    await openLibrary();

    expect(dropZone()).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Content", pressed: true }),
    ).toBeInTheDocument();
  });

  it("imports a file chosen with the file picker", async () => {
    const user = await openLibrary();

    await user.upload(fileInput(), makeFile("photo.png"));

    const items = await resultItems();
    expect(items).toHaveLength(1);
    expect(within(items[0]).getByText("photo.png")).toBeInTheDocument();
    expect(within(items[0]).getByText("Imported")).toBeInTheDocument();
    expect(importRequests()).toEqual([
      {
        method: "POST",
        path: `/projects/${project.id}/contents`,
        body: { files: ["photo.png"] },
      },
    ]);
  });

  it("imports a file dropped on the drop zone", async () => {
    await openLibrary();

    dropFiles([makeFile("clip.mp4")]);

    const [item] = await resultItems();
    expect(within(item).getByText("clip.mp4")).toBeInTheDocument();
    expect(within(item).getByText("Imported")).toBeInTheDocument();
    expect(api.contents.map((content) => content.media_type)).toEqual([
      "video",
    ]);
  });

  it("disables importing for inactive projects", async () => {
    const inactive = api.addProject({ name: "Old", is_active: false });
    await openLibrary(inactive);

    expect(
      screen.getByText("Reactivate the project to import content."),
    ).toBeInTheDocument();
    expect(fileInput()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose files" })).toBeDisabled();

    dropFiles([makeFile("photo.png")]);

    expect(importRequests()).toEqual([]);
  });
});

describe("Batch import (US2)", () => {
  it("imports several files one request at a time and groups the results", async () => {
    const user = await openLibrary();

    await user.upload(fileInput(), [
      makeFile("a.png"),
      makeFile("notes.txt"),
      makeFile("b.mp4"),
      makeFile("empty.jpg", 0),
    ]);

    expect(
      await screen.findByText("2 imported · 0 duplicates · 2 rejected"),
    ).toBeInTheDocument();
    const items = await resultItems();
    expect(importRequests().map((request) => request.body)).toEqual([
      { files: ["a.png"] },
      { files: ["notes.txt"] },
      { files: ["b.mp4"] },
      { files: ["empty.jpg"] },
    ]);
    expect(items.map((item) => item.className)).toEqual([
      "result-imported",
      "result-rejected",
      "result-imported",
      "result-rejected",
    ]);
    expect(
      within(items[1]).getByText(/Unsupported file format/),
    ).toBeInTheDocument();
    expect(within(items[3]).getByText(/The file is empty/)).toBeInTheDocument();
  });

  it("shows the progress and blocks a second import while busy", async () => {
    let release: () => void = () => undefined;
    api.importGate = () =>
      new Promise<void>((resolve) => {
        release = resolve;
      });
    await openLibrary();

    dropFiles([makeFile("a.png"), makeFile("b.png")]);

    expect(await screen.findByText("Importing 1 of 2…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose files" })).toBeDisabled();
    dropFiles([makeFile("c.png")]);
    release();
    expect(await screen.findByText("Importing 2 of 2…")).toBeInTheDocument();
    api.importGate = null;
    release();

    expect(await resultItems()).toHaveLength(2);
    expect(importRequests()).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Choose files" })).toBeEnabled();
  });

  it("refuses batches over the limit without sending anything", async () => {
    await openLibrary();

    dropFiles(Array.from({ length: 101 }, (_, i) => makeFile(`${i}.png`)));

    expect(
      await screen.findByText("You can import at most 100 files at once."),
    ).toBeInTheDocument();
    expect(importRequests()).toEqual([]);
  });

  it("keeps going when one file hits a network error", async () => {
    const user = await openLibrary();
    api.failNetworkNext();

    await user.upload(fileInput(), [makeFile("a.png"), makeFile("b.png")]);

    await waitForImport();
    const items = await resultItems();
    expect(items.map((item) => item.className)).toEqual([
      "result-rejected",
      "result-imported",
    ]);
    expect(
      within(items[0]).getByText(/Could not reach the server/),
    ).toBeInTheDocument();
    expect(importRequests()).toHaveLength(2);
  });

  it("stops the remaining files when the project becomes inactive", async () => {
    const user = await openLibrary();
    api.failNext(409, {
      error: {
        code: "project_inactive",
        message: "Reactivate the project before importing content.",
        fields: [],
      },
    });

    await user.upload(fileInput(), [makeFile("a.png"), makeFile("b.png")]);

    expect(
      await screen.findByText(
        "Reactivate the project before importing content.",
      ),
    ).toBeInTheDocument();
    expect(importRequests()).toHaveLength(1);
  });
});

describe("Duplicates (US3)", () => {
  it("marks files that already exist in the project", async () => {
    api.addContent({
      project_id: project.id,
      original_filename: "photo.png",
      size_bytes: 10,
      title: "Summer teaser",
    });
    const user = await openLibrary();

    await user.upload(fileInput(), makeFile("photo.png", 10));

    await waitForImport();
    const [item] = await resultItems();
    expect(item).toHaveClass("result-duplicate");
    expect(within(item).getByText("Duplicate")).toBeInTheDocument();
    expect(
      within(item).getByText(/Already in this project as “Summer teaser”/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("0 imported · 1 duplicate · 0 rejected"),
    ).toBeInTheDocument();
  });
});

describe("Library (US4)", () => {
  function grid() {
    return screen.getByRole("list", { name: "Content library" });
  }

  it("shows an empty state", async () => {
    await openLibrary();

    expect(
      await screen.findByText(
        "No content yet. Drop images or videos here or choose files to import them.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a card per content with preview, type, name and date", async () => {
    api.addContent({
      project_id: project.id,
      original_filename: "photo.png",
      title: "Summer teaser",
    });
    api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      original_filename: "clip.mp4",
    });
    api.addContent({ project_id: api.addProject({ name: "Other" }).id });
    await openLibrary();

    await screen.findByRole("list", { name: "Content library" });
    const cards = within(grid()).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    // Newest first.
    expect(within(cards[0]).getByText("clip.mp4")).toBeInTheDocument();
    expect(within(cards[0]).getByText("Video")).toBeInTheDocument();
    expect(cards[0].querySelector("video")).not.toBeNull();
    expect(within(cards[1]).getByText("Summer teaser")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Image")).toBeInTheDocument();
    expect(cards[1].querySelector("img")).toHaveAttribute(
      "src",
      expect.stringMatching(/^\/api\/contents\/\d+\/file$/),
    );
    expect(
      within(cards[1]).getByText(
        new Date("2026-10-05T10:00:00Z").toLocaleString(),
      ),
    ).toBeInTheDocument();
  });

  it("shows the full metadata of a selected content", async () => {
    api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      original_filename: "reel.mp4",
      title: "Reel",
      description: "A short reel",
      hashtags: ["l4i4", "summer"],
      size_bytes: 18_734_211,
      width: 1080,
      height: 1920,
      duration_seconds: 14.5,
    });
    const user = await openLibrary();

    await user.click(await screen.findByRole("button", { name: /Reel/ }));

    const detail = screen.getByRole("region", { name: "Content details" });
    expect(within(detail).getByText("reel.mp4")).toBeInTheDocument();
    expect(within(detail).getByText("A short reel")).toBeInTheDocument();
    expect(within(detail).getByText("#l4i4 #summer")).toBeInTheDocument();
    expect(within(detail).getByText("18.7 MB")).toBeInTheDocument();
    expect(within(detail).getByText("1080 × 1920")).toBeInTheDocument();
    expect(within(detail).getByText("0:15")).toBeInTheDocument();
    expect(within(detail).getByText("Video")).toBeInTheDocument();
    expect(detail.querySelector("video[controls]")).not.toBeNull();
  });

  it("warns when the stored file is missing", async () => {
    api.addContent({
      project_id: project.id,
      original_filename: "gone.png",
      file_available: false,
    });
    await openLibrary();

    const [card] = within(
      await screen.findByRole("list", { name: "Content library" }),
    ).getAllByRole("listitem");
    expect(within(card).getByText("File not available")).toBeInTheDocument();
    expect(card.querySelector("img")).toBeNull();
  });

  it("reloads the library after an import", async () => {
    const user = await openLibrary();
    await screen.findByText(/No content yet/);

    await user.upload(fileInput(), makeFile("new.png"));

    expect(
      await within(
        await screen.findByRole("list", { name: "Content library" }),
      ).findByText("new.png"),
    ).toBeInTheDocument();
  });

  it("opens the existing content from a duplicate result", async () => {
    api.addContent({
      project_id: project.id,
      original_filename: "photo.png",
      size_bytes: 10,
      title: "Original",
    });
    const user = await openLibrary();
    await user.upload(fileInput(), makeFile("photo.png", 10));
    await waitForImport();

    await user.click(screen.getByRole("button", { name: "Open" }));

    const detail = screen.getByRole("region", { name: "Content details" });
    expect(within(detail).getByText("photo.png")).toBeInTheDocument();
  });

  it("handles a library of 200 contents", async () => {
    for (let i = 0; i < 200; i++) {
      api.addContent({ project_id: project.id, original_filename: `${i}.png` });
    }
    const user = await openLibrary();

    const list = await screen.findByRole("list", { name: "Content library" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(200);

    await user.click(within(list).getByText("0.png"));

    const detail = screen.getByRole("region", { name: "Content details" });
    expect(
      within(detail).getByRole("heading", { name: "0.png" }),
    ).toBeInTheDocument();
  });
});

describe("Metadata editing (US5)", () => {
  async function openContent(title = "Reel") {
    api.addContent({ project_id: project.id, title });
    const user = await openLibrary();
    await user.click(
      await screen.findByRole("button", { name: new RegExp(title) }),
    );
    return user;
  }

  function detail() {
    return screen.getByRole("region", { name: "Content details" });
  }

  it("edits title, description and hashtags", async () => {
    const user = await openContent();

    await user.click(within(detail()).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit content" });
    await user.clear(within(form).getByLabelText("Title"));
    await user.type(within(form).getByLabelText("Title"), "Summer teaser");
    await user.type(within(form).getByLabelText("Description"), "First reel");
    await user.type(
      within(form).getByLabelText("Hashtags"),
      "#l4i4 summer, reels",
    );
    await user.click(within(form).getByRole("button", { name: "Save" }));

    const patchRequest = api.requests.find((r) => r.method === "PATCH");
    expect(patchRequest?.body).toEqual({
      title: "Summer teaser",
      description: "First reel",
      hashtags: ["#l4i4", "summer", "reels"],
    });
    expect(
      await within(detail()).findByText("#l4i4 #summer #reels"),
    ).toBeInTheDocument();
    expect(within(detail()).getByText("First reel")).toBeInTheDocument();
    expect(
      within(detail()).getByRole("heading", { name: "Summer teaser" }),
    ).toBeInTheDocument();
  });

  it("shows field errors and keeps what was typed", async () => {
    const user = await openContent();
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

    await user.click(within(detail()).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Edit content" });
    await user.type(within(form).getByLabelText("Hashtags"), "#ok");
    await user.click(within(form).getByRole("button", { name: "Save" }));

    expect(
      await within(form).findByText(
        "Hashtags cannot be empty or contain spaces.",
      ),
    ).toBeInTheDocument();
    expect(within(form).getByLabelText("Hashtags")).toHaveValue("#ok");
  });

  it("offers no way to delete content", async () => {
    await openContent();

    expect(
      screen.queryByRole("button", { name: /delete|remove/i }),
    ).not.toBeInTheDocument();
  });
});
