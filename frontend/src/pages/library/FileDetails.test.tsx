import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import type { Content } from "../../types.ts";
import FileDetails from "./FileDetails.tsx";

let api: FakeApi;
let content: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  content = api.addContent({
    project_id: api.addProject({ name: "L4i4" }).id,
    original_filename: "photo.png",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Renders like the detail does and opens it. */
async function openFile() {
  render(<FileDetails content={content} />);
  const user = userEvent.setup();
  const toggle = screen.getByRole("button", { name: "File details" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  return user;
}

it("lists the file facts with the checksums last", async () => {
  await openFile();

  const terms = screen.getAllByRole("term").map((term) => term.textContent);
  expect(terms).toEqual([
    "File name",
    "Format",
    "Dimensions",
    "Size",
    "Published version",
    "Checksum",
  ]);
  expect(screen.getByText("photo.png")).toBeInTheDocument();
  expect(screen.getByText("8 × 6")).toBeInTheDocument();
});

it("offers only Inspect metadata: Clean metadata lives in the detail header", async () => {
  await openFile();

  expect(screen.getByText(/Metadata not checked yet/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Inspect metadata" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Clean metadata/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Remove metadata/ })).toBeNull();
});

it("describes a published clean copy and points a missing one to Clean metadata", async () => {
  content = {
    ...content,
    metadata_status: "sanitized",
    publish_file: { ...content.publish_file, version: "clean_copy" },
  };
  const view = render(<FileDetails content={content} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "File details" }));

  expect(
    screen.getByText(/the clean copy is published instead/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Clean copy without metadata/)).toBeInTheDocument();
  expect(screen.getByText("Clean copy checksum")).toBeInTheDocument();

  view.rerender(
    <FileDetails
      content={{
        ...content,
        publish_file: { ...content.publish_file, available: false },
      }}
    />,
  );
  expect(
    screen.getByText(/Clean metadata again to recreate it/),
  ).toBeInTheDocument();
});

it("shows the error of a failed inspection", async () => {
  const user = await openFile();
  vi.stubGlobal("fetch", async () =>
    Response.json(
      {
        error: {
          code: "media_unavailable",
          message: "The media file is not available.",
        },
      },
      { status: 404 },
    ),
  );

  await user.click(screen.getByRole("button", { name: "Inspect metadata" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The media file is not available.",
  );
});

it("tells an already clean original apart", async () => {
  content = { ...content, metadata_status: "clean" };
  await openFile();

  expect(
    screen.getByText(/already clean, so it is published as is/),
  ).toBeInTheDocument();
  expect(screen.getByText("Original file")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Clean metadata" })).toBeNull();
});

it("lists the metadata found in the original and the clean copy", async () => {
  content = { ...content, metadata_status: "sanitized" };
  api.metadataReports[content.id] = {
    original: {
      inspected: true,
      reason: null,
      findings: [
        {
          category: "comfyui",
          label: "ComfyUI workflow",
          keys: ["prompt", "workflow"],
        },
      ],
    },
    publish_copy: { inspected: true, reason: null, findings: [] },
  };
  const user = await openFile();

  await user.click(screen.getByRole("button", { name: "Inspect metadata" }));

  const original = await screen.findByRole("list", {
    name: "Original metadata",
  });
  expect(original).toHaveTextContent("ComfyUI workflow (prompt, workflow)");
  expect(screen.getByText("No sensitive metadata found")).toBeInTheDocument();
});
