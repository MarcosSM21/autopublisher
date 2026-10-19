import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeApi, TG_CODE, TG_PASSWORD } from "../test-fake-api.ts";
import type { Account, Project } from "../types.ts";
import { setHealth } from "../pages/publish/test-publish.ts";
import { renderRoute } from "../test-utils.tsx";
import TelegramConnectionPanel from "./TelegramConnectionPanel.tsx";

let api: FakeApi;
let project: Project;
let account: Account;

beforeEach(() => {
  api = new FakeApi();
  api.install();
  project = api.addProject({ name: "Cyber" });
  account = api.addAccount({
    project_id: project.id,
    platform: "telegram",
    handle: "mychannel",
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPanel() {
  render(<TelegramConnectionPanel account={account} projectActive={true} />);
  return userEvent.setup();
}

function telegramRequests(suffix: string) {
  return api.requests.filter((r) => r.path.endsWith(suffix));
}

describe("TelegramConnectionPanel", () => {
  it("connects with phone, code and two-step password", async () => {
    api.telegramRequiresPassword = true;
    const user = renderPanel();

    const phone = await screen.findByLabelText(/Phone number/);
    await user.type(phone, "+34 600 111 222");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(telegramRequests("/login/start")[0].body).toEqual({
      phone: "+34600111222",
    });

    const code = await screen.findByLabelText(/Code Telegram sent to/);
    expect(code).toHaveValue("");
    await user.type(code, TG_CODE);
    await user.click(screen.getByRole("button", { name: "Continue" }));

    const password = await screen.findByLabelText(
      "Two-step verification password",
    );
    await user.type(password, TG_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Test User")).toBeInTheDocument();
    expect(screen.getByText("@tester")).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/)).not.toBeInTheDocument();
    // What was typed is never left in the page.
    expect(document.body.innerHTML).not.toContain(TG_PASSWORD);
    expect(document.body.innerHTML).not.toContain(TG_CODE);
  });

  it("shows login errors and can cancel a pending login", async () => {
    const user = renderPanel();
    await user.type(await screen.findByLabelText(/Phone number/), "+34600");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText(/Code Telegram/), "11111");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The code is not correct.",
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByLabelText(/Phone number/)).toBeInTheDocument();
  });

  it("chooses the destination channel", async () => {
    api.setTelegramConnection(account.id, null);
    const user = renderPanel();
    expect(
      await screen.findByText(/none chosen yet/, { exact: false }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Choose channel" }));
    await user.selectOptions(
      await screen.findByLabelText("Channel"),
      "1900000002",
    );
    await user.click(screen.getByRole("button", { name: "Save channel" }));

    expect(await screen.findByText("Private")).toBeInTheDocument();
    expect(telegramRequests("/channel")[0].body).toEqual({
      channel_id: "1900000002",
    });
  });

  it("explains why the channel cannot change while publications are pending", async () => {
    api.setTelegramConnection(account.id);
    api.addPublication({
      content_id: null,
      account_id: account.id,
      scheduled_at: "2100-01-01T10:00:00Z",
    });
    renderPanel();
    expect(
      await screen.findByRole("button", { name: "Change channel" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Finish or cancel the pending Telegram publications/),
    ).toBeInTheDocument();
  });

  it("shows busy and other errors from Telegram", async () => {
    api.setTelegramConnection(account.id);
    api.telegramErrors.set("/verify", {
      status: 409,
      code: "telegram_busy",
      message: "Telegram is busy with another operation of this account.",
    });
    const user = renderPanel();
    await user.click(
      await screen.findByRole("button", { name: "Verify connection" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Telegram is busy with another operation of this account.",
    );
    await user.click(screen.getByRole("button", { name: "Verify connection" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Connection verified.",
    );
  });

  it("disconnects after confirmation", async () => {
    api.setTelegramConnection(account.id);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = renderPanel();
    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(await screen.findByLabelText(/Phone number/)).toBeInTheDocument();
  });
});

describe("Telegram publications", () => {
  it("offers Telegram accounts for new text posts", async () => {
    setHealth(api, project.id);
    renderRoute(`/p/${project.id}/posts/new`);
    const destinations = await screen.findByRole("group", {
      name: "Destinations",
    });
    expect(
      within(destinations).getByRole("checkbox", { name: /mychannel/ }),
    ).toBeEnabled();
  });

  it("can publish a Telegram text post now", async () => {
    api.setTelegramConnection(account.id);
    setHealth(api, project.id);
    const publication = api.addPublication({
      content_id: null,
      account_id: account.id,
      description_override: "Hello",
      hashtags_override: [],
    });
    renderRoute(`/p/${project.id}/posts/new?posts=${publication.id}`);
    const card = await screen.findByRole("region", { name: /^Telegram/ });
    expect(await within(card).findByText("Ready")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Publish to 1 destination" }),
    ).toBeEnabled();
  });
});
