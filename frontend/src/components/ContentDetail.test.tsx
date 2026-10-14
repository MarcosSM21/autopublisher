import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import ContentDetail from "./ContentDetail.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ContentDetail preview", () => {
  it("still renders the same large video preview", () => {
    const project = api.addProject({ name: "Cyber" });
    const video = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      original_filename: "clip.mp4",
    });

    const { container } = render(
      <ContentDetail
        project={project}
        content={video}
        onChanged={async () => {}}
        onOpenQueue={() => {}}
      />,
    );

    const preview = container.querySelector("video.preview")!;
    expect(preview).toHaveAttribute("src", video.file_url);
    expect(preview).toHaveAttribute("controls");
    expect(preview).toHaveAttribute("preload", "metadata");
  });
});
