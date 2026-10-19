import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { TikTokPublicationOptions } from "../../types.ts";
import TikTokDeclaration from "./TikTokDeclaration.tsx";
import { useTikTokDeclaration } from "./tiktok-declaration.ts";

afterEach(cleanup);

type Options = Pick<
  TikTokPublicationOptions,
  "fingerprint" | "declaration" | "consent"
>;

function options(values: Partial<Options> = {}): Options {
  return {
    fingerprint: "fp-1",
    declaration: { version: "v1", text: "By posting, you agree.", links: [] },
    // A consent the backend already recorded must not pre-check the box.
    consent: { state: "valid", consented_at: "2026-10-05T10:00:00Z" },
    ...values,
  };
}

function Owner({ current }: { current: Options }) {
  const declaration = useTikTokDeclaration();
  return <TikTokDeclaration options={current} {...declaration} />;
}

function checkbox() {
  return screen.getByRole("checkbox", { name: /I agree to the declaration/ });
}

describe("TikTok declaration", () => {
  it("starts unchecked even with a valid persisted consent", () => {
    render(<Owner current={options()} />);
    expect(checkbox()).not.toBeChecked();
  });

  it.each([
    ["a new fingerprint", { fingerprint: "fp-2" }],
    [
      "a new declaration version",
      {
        declaration: {
          version: "v2",
          text: "By posting, you agree.",
          links: [],
        },
      },
    ],
  ])("unchecks itself after %s", async (_label, change) => {
    const user = userEvent.setup();
    const { rerender } = render(<Owner current={options()} />);

    await user.click(checkbox());
    expect(checkbox()).toBeChecked();

    rerender(<Owner current={options(change)} />);
    expect(checkbox()).not.toBeChecked();
  });

  it("cannot be checked while the options are incomplete", () => {
    render(<Owner current={options({ fingerprint: null })} />);
    expect(checkbox()).toBeDisabled();
    expect(
      screen.getByText("Complete the TikTok details first."),
    ).toBeInTheDocument();
  });
});
