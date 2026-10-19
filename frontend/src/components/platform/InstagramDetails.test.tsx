import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FakeApi } from "../../test-fake-api.ts";
import { card, renderCard, writes } from "./test-card.tsx";

let api: FakeApi;

beforeEach(() => {
  api = new FakeApi();
  api.install();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("asks for AI-generated content and saves alt text only on blur", async () => {
  const project = api.addProject({ name: "Cyber" });
  const image = api.addContent({ project_id: project.id });
  const account = api.addAccount({
    project_id: project.id,
    platform: "instagram",
    handle: "l4i4",
  });
  api.setInstagramConnection(account.id);
  const publication = api.addPublication({
    content_id: image.id,
    account_id: account.id,
  });
  const { user } = renderCard(publication);
  const region = card(/Instagram/);

  expect(
    await within(region).findByText(
      "Instagram needs 1 detail: AI-generated content.",
    ),
  ).toBeInTheDocument();
  const ai = within(region).getByRole("group", {
    name: "AI-generated content?",
  });
  expect(within(ai).getByRole("radio", { name: "No" })).not.toBeChecked();

  const alt = within(region).getByLabelText("Alt text");
  await user.type(alt, "A sunset");
  expect(writes(api)).toHaveLength(0);
  await user.tab();
  await within(region).findByText("Saved");
  expect(writes(api)).toEqual([
    {
      method: "PUT",
      path: `/publications/${publication.id}/instagram-options`,
      body: { is_ai_generated: null, alt_text: "A sunset" },
    },
  ]);

  // Leaving the field again without changes sends nothing.
  await user.click(alt);
  await user.tab();
  await user.click(within(ai).getByRole("radio", { name: "No" }));
  expect(await screen.findByText("Ready")).toBeInTheDocument();
  expect(writes(api).map((request) => request.body)).toEqual([
    { is_ai_generated: null, alt_text: "A sunset" },
    { is_ai_generated: false, alt_text: "A sunset" },
  ]);
});
