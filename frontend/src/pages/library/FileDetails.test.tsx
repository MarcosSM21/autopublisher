import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getContent } from "../../api.ts";
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

/** Renders like the detail does, reloaded after a change, and opens it. */
async function openFile() {
  const view = render(<FileDetails content={content} onChanged={reload} />);
  async function reload() {
    content = await getContent(content.id);
    view.rerender(<FileDetails content={content} onChanged={reload} />);
  }
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

it("removes the metadata and then publishes the clean copy", async () => {
  const user = await openFile();
  expect(screen.getByText(/Metadata not checked yet/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Remove metadata" }));

  expect(
    await screen.findByText(/the clean copy is published instead/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Clean copy without metadata/)).toBeInTheDocument();
  expect(screen.getByText("Clean copy checksum")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove metadata" })).toBeNull();
});

it("shows the error of a rejected removal", async () => {
  api.removeMetadataResult[content.id] = {
    status: 409,
    code: "content_publishing",
    message: "This content is being published.",
  };
  const user = await openFile();

  await user.click(screen.getByRole("button", { name: "Remove metadata" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This content is being published.",
  );
});

it("tells an already clean original apart and hides the action", async () => {
  content = { ...content, metadata_status: "clean" };
  await openFile();

  expect(
    screen.getByText(/already clean, so it is published as is/),
  ).toBeInTheDocument();
  expect(screen.getByText("Original file")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove metadata" })).toBeNull();
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
