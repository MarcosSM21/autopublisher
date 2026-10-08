import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi } from "../test-fake-api.ts";
import AutomationStatus from "./AutomationStatus.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function puts() {
  return api.requests.filter(
    (request) => request.method === "PUT" && request.path === "/automation",
  );
}

describe("automation status", () => {
  it("shows that automation is running and when it last checked", async () => {
    render(<AutomationStatus />);

    expect(await screen.findByText("Automation running")).toBeInTheDocument();
    expect(screen.getByText(/Last check/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "AutoPublisher must be running to publish automatically.",
      ),
    ).toBeInTheDocument();
  });

  it("pauses and resumes automation", async () => {
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(<AutomationStatus onChanged={onChanged} />);

    await user.click(
      await screen.findByRole("button", { name: "Pause automation" }),
    );
    expect(await screen.findByText("Automation paused")).toBeInTheDocument();
    expect(puts().map((request) => request.body)).toEqual([{ paused: true }]);
    expect(onChanged).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Resume automation" }));
    expect(await screen.findByText("Automation running")).toBeInTheDocument();
    expect(puts().map((request) => request.body)).toEqual([
      { paused: true },
      { paused: false },
    ]);
  });

  it("shows a paused automation after loading", async () => {
    api.automation = { ...api.automation, paused: true };
    render(<AutomationStatus />);

    expect(await screen.findByText("Automation paused")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Resume automation" }),
    ).toBeInTheDocument();
  });

  it("explains when the scheduler is not running", async () => {
    api.automation = { ...api.automation, running: false };
    render(<AutomationStatus />);

    await waitFor(() =>
      expect(screen.getByText("Scheduler not running")).toBeInTheDocument(),
    );
  });
});
