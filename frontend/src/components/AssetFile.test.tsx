import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getContent } from "../api.ts";
import { FakeApi } from "../test-fake-api.ts";
import type { Content } from "../types.ts";
import AssetFile from "./AssetFile.tsx";

let api: FakeApi;
let content: Content;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  content = api.addContent({ project_id: api.addProject({ name: "L4i4" }).id });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Renders like the detail does: reloaded from the API after a change. */
function renderFile() {
  const view = render(<AssetFile content={content} onChanged={reload} />);
  async function reload() {
    content = await getContent(content.id);
    view.rerender(<AssetFile content={content} onChanged={reload} />);
  }
  return view;
}

it("removes the metadata and then publishes the clean copy", async () => {
  renderFile();
  expect(screen.getByText(/Metadata not checked yet/)).toBeInTheDocument();

  await userEvent.click(
    screen.getByRole("button", { name: "Remove metadata" }),
  );

  expect(
    await screen.findByText(/the clean copy is published instead/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/clean copy \(without metadata\)/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove metadata" })).toBeNull();
});

it("shows the error of a rejected removal", async () => {
  api.removeMetadataResult[content.id] = {
    status: 409,
    code: "content_publishing",
    message: "This content is being published.",
  };
  renderFile();

  await userEvent.click(
    screen.getByRole("button", { name: "Remove metadata" }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This content is being published.",
  );
});

it("tells an already clean original apart and hides the action", () => {
  content = { ...content, metadata_status: "clean" };
  renderFile();

  expect(
    screen.getByText(/already clean, so it is published as is/),
  ).toBeInTheDocument();
  expect(screen.getByText("original file")).toBeInTheDocument();
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
  renderFile();

  await userEvent.click(
    screen.getByRole("button", { name: "Inspect metadata" }),
  );

  const original = await screen.findByRole("list", {
    name: "Original metadata",
  });
  expect(original).toHaveTextContent("ComfyUI workflow (prompt, workflow)");
  expect(screen.getByText("No sensitive metadata found")).toBeInTheDocument();
});
