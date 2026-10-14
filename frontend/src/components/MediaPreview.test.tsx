import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import MediaPreview from "./MediaPreview.tsx";

afterEach(cleanup);

const VIDEO = {
  media_type: "video" as const,
  file_url: "/api/contents/7/file",
  file_available: true,
};

describe("MediaPreview", () => {
  it("shows an image from the file URL", () => {
    const { container } = render(
      <MediaPreview content={{ ...VIDEO, media_type: "image" }} />,
    );

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/api/contents/7/file",
    );
  });

  it("plays a large video with controls", () => {
    const { container } = render(<MediaPreview content={VIDEO} large />);

    const video = container.querySelector("video")!;
    expect(video).toHaveAttribute("src", "/api/contents/7/file");
    expect(video).toHaveAttribute("controls");
  });

  it("shows a small muted video without controls", () => {
    const { container } = render(<MediaPreview content={VIDEO} />);

    const video = container.querySelector("video")!;
    expect(video).not.toHaveAttribute("controls");
    expect(video.muted).toBe(true);
  });

  it("explains a missing file", () => {
    render(<MediaPreview content={{ ...VIDEO, file_available: false }} />);

    expect(screen.getByText("File not available")).toBeInTheDocument();
  });

  it("explains a preview the browser cannot play", () => {
    const { container } = render(<MediaPreview content={VIDEO} large />);

    fireEvent.error(container.querySelector("video")!);

    expect(
      screen.getByText("Preview not available in this browser"),
    ).toBeInTheDocument();
  });
});
