import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AutoPublishState, Publication } from "../types.ts";
import AutoPublishBadge from "./AutoPublishBadge.tsx";

afterEach(cleanup);

function publication(
  state: AutoPublishState | null,
  error: Publication["auto_publish_error"] = null,
): Pick<Publication, "auto_publish_state" | "auto_publish_error"> {
  return { auto_publish_state: state, auto_publish_error: error };
}

describe("auto-publish badge", () => {
  it.each([
    ["waiting", ["Auto-publish enabled", "Waiting for its time"]],
    ["due", ["Auto-publish enabled", "Starting soon"]],
    ["paused", ["Auto-publish enabled", "Automation paused"]],
    ["disabled", ["Auto-publish disabled"]],
    [
      "overdue",
      ["Missed automatic publishing window", "Publish now or reschedule"],
    ],
  ] as const)("shows the %s state", (state, texts) => {
    render(<AutoPublishBadge publication={publication(state)} />);

    for (const text of texts) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("never shows a missed window for a disarmed publication", () => {
    render(<AutoPublishBadge publication={publication("disabled")} />);

    expect(
      screen.queryByText("Missed automatic publishing window"),
    ).not.toBeInTheDocument();
  });

  it("shows nothing for publications that are not scheduled", () => {
    const { container } = render(
      <AutoPublishBadge publication={publication(null)} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("adds the reason of the last automatic failure", () => {
    render(
      <AutoPublishBadge
        publication={publication("due", {
          code: "not_connected",
          message: "Connect this YouTube account before publishing.",
          failed_at: "2026-10-07T18:00:30Z",
        })}
      />,
    );

    expect(
      screen.getByText(
        "Could not start automatically: Connect this YouTube account before publishing.",
      ),
    ).toBeInTheDocument();
  });
});
