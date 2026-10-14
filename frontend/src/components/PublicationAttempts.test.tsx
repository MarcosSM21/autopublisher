import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import type { Account, Content, Project, Publication } from "../types.ts";
import PublicationAttempts from "./PublicationAttempts.tsx";

let api: FakeApi;
let project: Project;
let image: Content;
let instagram: Account;
let youtube: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  image = api.addContent({
    project_id: project.id,
    media_type: "image",
    media_format: "jpeg",
    original_filename: "poster.jpg",
    description: "Summer drop.",
    hashtags: ["cyber"],
    size_bytes: 1_000,
  });
  instagram = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "cyberstudio",
  });
  youtube = api.addAccount({
    project_id: project.id,
    platform: "youtube",
    handle: "cyberchannel",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function started(account: Account): number {
  const publication = api.addPublication({
    content_id: image.id,
    account_id: account.id,
  });
  const record = api.publications.find((p) => p.id === publication.id)!;
  api.startAttempt(record);
  return publication.id;
}

function view(publicationId: number): Publication {
  const record = api.publications.find((p) => p.id === publicationId)!;
  return api.publicationView(record);
}

describe("platform-aware attempts", () => {
  it("links to Instagram after an Instagram success", async () => {
    const id = started(instagram);
    api.succeedAttempt(id);

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      await screen.findByRole("link", { name: "Open on Instagram" }),
    ).toHaveAttribute("href", "https://www.instagram.com/p/FakePost001/");
    expect(screen.queryByText(/Open on YouTube/)).not.toBeInTheDocument();
  });

  it("still links to YouTube for YouTube attempts", async () => {
    const id = started(youtube);
    api.succeedAttempt(id);

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      await screen.findByRole("link", { name: "Open on YouTube" }),
    ).toBeInTheDocument();
  });

  it("shows no link and the warning when the post has no remote identity", async () => {
    const id = started(instagram);
    api.succeedAttempt(id, {
      externalUrl: null,
      warnings: [
        {
          code: "remote_identity_unavailable",
          message: "Instagram confirmed the post was published.",
        },
      ],
    });

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      await screen.findByText("Instagram confirmed the post was published."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the cleanup warning without changing the result", async () => {
    const id = started(instagram);
    api.succeedAttempt(id, {
      warnings: [
        {
          code: "temporary_media_cleanup_failed",
          message: "The temporary copy could not be deleted yet.",
        },
      ],
    });

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      await screen.findByText("The temporary copy could not be deleted yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open on Instagram" }),
    ).toBeInTheDocument();
  });
});

describe("progress", () => {
  it("shows the phase without a percentage while Instagram processes", () => {
    const id = started(instagram);
    api.progressAttempt(id, 1_000);
    api.setStage(id, "processing");

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Processing on Instagram",
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("shows publishing on Instagram while finalizing", () => {
    const id = started(instagram);
    api.setStage(id, "finalizing");

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Publishing on Instagram",
    );
  });

  it("never shows 100% while the attempt is running", () => {
    const id = started(instagram);
    api.progressAttempt(id, 1_000);

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      screen.getByRole("progressbar", { name: "Upload progress" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/99%/)).toBeInTheDocument();
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });
});

describe("manual review", () => {
  it("asks to check Instagram with the account, caption and time", () => {
    const id = started(instagram);
    api.failAttempt(
      id,
      "instagram_publish_uncertain",
      "Check Instagram.",
      false,
    );

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByText("Check Instagram")).toBeInTheDocument();
    expect(screen.getByText("@cyber.studio")).toBeInTheDocument();
    expect(screen.getByText(/Summer drop\./)).toBeInTheDocument();
    expect(screen.queryByText("Check YouTube Studio")).not.toBeInTheDocument();
  });

  it("asks to check Threads with the account, exact text and time", () => {
    const threads = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "cyberstudio",
    });
    const publication = api.addPublication({
      content_id: null,
      account_id: threads.id,
      description_override: "Hello Threads",
      hashtags_override: ["cyber"],
    });
    const record = api.publications.find((p) => p.id === publication.id)!;
    api.startAttempt(record);
    api.failAttempt(
      publication.id,
      "threads_publish_uncertain",
      "Threads did not confirm whether the post was published.",
      false,
    );

    render(<PublicationAttempts publication={view(publication.id)} />);

    expect(screen.getByText("Check Threads")).toBeInTheDocument();
    expect(screen.getByText("@cyber.studio")).toBeInTheDocument();
    expect(screen.getByText("Text")).toBeInTheDocument();
    expect(document.querySelector(".review .caption")?.textContent).toBe(
      "Hello Threads\n\n#cyber",
    );
    expect(screen.queryByText("Check Instagram")).not.toBeInTheDocument();
    expect(screen.queryByText("Check YouTube Studio")).not.toBeInTheDocument();
  });

  it("links to Threads only with an official permalink", () => {
    const threads = api.addAccount({
      project_id: project.id,
      platform: "threads",
      handle: "cyberstudio",
    });
    const publication = api.addPublication({
      content_id: null,
      account_id: threads.id,
      description_override: "Hello",
      hashtags_override: [],
    });
    const record = api.publications.find((p) => p.id === publication.id)!;
    api.startAttempt(record);
    api.succeedAttempt(publication.id, {
      externalUrl: null,
      warnings: [
        {
          code: "permalink_unavailable",
          message: "Threads did not return the link of the post.",
        },
      ],
    });

    render(<PublicationAttempts publication={view(publication.id)} />);

    expect(
      screen.getByText("Threads did not return the link of the post."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("TikTok attempts", () => {
  function tiktokStarted(): number {
    const tiktok = api.addAccount({
      project_id: project.id,
      platform: "tiktok",
      handle: "cyberstudio",
    });
    const clip = api.addContent({
      project_id: project.id,
      media_type: "video",
      media_format: "mp4",
      description: "Summer drop.",
      hashtags: ["cyber"],
    });
    const publication = api.addPublication({
      content_id: clip.id,
      account_id: tiktok.id,
    });
    api.startAttempt(api.publications.find((p) => p.id === publication.id)!);
    return publication.id;
  }

  it("shows uploading progress by confirmed bytes", () => {
    const id = tiktokStarted();
    api.progressAttempt(id, 500);

    render(<PublicationAttempts publication={view(id)} />);

    expect(
      screen.getByRole("progressbar", { name: "Upload progress" }),
    ).toBeInTheDocument();
  });

  it("shows that TikTok is processing while finalizing", () => {
    const id = tiktokStarted();
    api.setStage(id, "finalizing");

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "TikTok is processing the video",
    );
  });

  it("finishes the upload during the last chunk", () => {
    const id = tiktokStarted();
    api.setStage(id, "final_chunk");

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByText(/%/)).toBeInTheDocument();
  });

  it("never links to TikTok without an official URL", () => {
    const id = tiktokStarted();
    api.succeedAttempt(id, {
      externalUrl: null,
      warnings: [
        {
          code: "tiktok_private_post_no_link",
          message: "TikTok does not return a link for private posts.",
        },
      ],
    });

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText("TikTok does not return a link for private posts."),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "tiktok_creator_cannot_post",
      "This TikTok account reached its daily posting limit.",
    ],
    [
      "tiktok_private_account_required",
      "TikTok only accepts posts to private accounts.",
    ],
    ["tiktok_video_rejected", "TikTok rejected the video."],
    ["tiktok_upload_expired", "The TikTok upload link expired."],
  ])("shows the message of %s", (code, message) => {
    const id = tiktokStarted();
    api.failAttempt(id, code, message, true);

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByText(/Nothing was published/)).toBeInTheDocument();
  });

  it("asks to check the TikTok profile after an uncertain result", () => {
    const id = tiktokStarted();
    api.failAttempt(
      id,
      "tiktok_result_uncertain",
      "TikTok did not confirm whether the video was published.",
      false,
    );

    render(<PublicationAttempts publication={view(id)} />);

    expect(screen.getByText("Check TikTok")).toBeInTheDocument();
    expect(
      screen.getByText(/check your TikTok profile before publishing again/),
    ).toBeInTheDocument();
    expect(document.querySelector(".review .caption")?.textContent).toBe(
      "Summer drop.\n\n#cyber",
    );
    expect(screen.queryByText("Check YouTube Studio")).not.toBeInTheDocument();
  });

  it("offers to check again while TikTok is still processing", async () => {
    const id = tiktokStarted();
    api.failAttempt(
      id,
      "tiktok_processing_pending",
      "TikTok was still processing the video.",
      false,
    );
    const onCheckAgain = vi.fn();

    render(
      <PublicationAttempts
        publication={view(id)}
        onCheckAgain={onCheckAgain}
      />,
    );
    screen.getByRole("button", { name: "Check again" }).click();

    expect(onCheckAgain).toHaveBeenCalled();
  });
});
