// Publishing activity and Published emphasis (Feature 026 T017–T020,
// contracts/ui.md §3). jsdom emits no `animationend`: cleanup is fired by hand.
import { cleanup, fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResultsSection from "../pages/publish/review/ResultsSection.tsx";
import type { PostStep } from "../pages/publish/usePublishTask.ts";
import type {
  AccountHealthState,
  PlatformStatus,
  PostDisplayState,
  Publication,
  PublicationAttempt,
} from "../types.ts";
import { ACCOUNT_STATUS, PLATFORM_STATUS, POST_STATUS } from "./status.ts";
import StatusBadge from "./StatusBadge.tsx";

afterEach(cleanup);

const POST_STATES = Object.keys(POST_STATUS) as PostDisplayState[];

function badgeOf(container: HTMLElement): HTMLElement {
  const badge = container.querySelector<HTMLElement>(".ap-badge");
  expect(badge).not.toBeNull();
  return badge!;
}

function endEmphasis(badge: HTMLElement) {
  fireEvent.animationEnd(badge, { animationName: "ap-badge-emphasis" });
}

describe("observed Publishing → Published (path A)", () => {
  function mount(state: PostDisplayState) {
    const view = render(<StatusBadge post={state} />);
    return {
      badge: () => badgeOf(view.container),
      show: (next: PostDisplayState) =>
        view.rerender(<StatusBadge post={next} />),
      unmount: view.unmount,
    };
  }

  it("case 1: mounting with Published is not a transition", () => {
    const { badge } = mount("published");
    expect(badge()).not.toHaveAttribute("data-emphasis");
  });

  it("case 2: Publishing → Published emphasises once", () => {
    const { badge, show } = mount("publishing");
    expect(badge()).not.toHaveAttribute("data-emphasis");
    show("published");
    expect(badge()).toHaveAttribute("data-emphasis");
    expect(badge()).toHaveTextContent("Published");
  });

  it("case 4: a poll that brings Published again never repeats it", () => {
    const { badge, show } = mount("publishing");
    show("published");
    endEmphasis(badge());
    expect(badge()).not.toHaveAttribute("data-emphasis");
    show("published");
    show("published");
    expect(badge()).not.toHaveAttribute("data-emphasis");
  });

  it("case 5: a remount with Published has no emphasis", () => {
    const first = mount("publishing");
    first.show("published");
    first.unmount();
    const { badge } = mount("published");
    expect(badge()).not.toHaveAttribute("data-emphasis");
  });

  it.each([
    "failed",
    "needs_action",
    "needs_review",
    "missed",
    "cancelled",
  ] as const)("case 6: Publishing → %s is never a success", (state) => {
    const { badge, show } = mount("publishing");
    show(state);
    expect(badge()).not.toHaveAttribute("data-emphasis");
  });

  it("a later state change ends an emphasis that never got its animationend", () => {
    const { badge, show } = mount("publishing");
    show("published");
    show("needs_review");
    expect(badge()).not.toHaveAttribute("data-emphasis");
  });
});

describe("emphasis cleanup", () => {
  function emphasised() {
    const view = render(<StatusBadge post="publishing" />);
    view.rerender(<StatusBadge post="published" />);
    return badgeOf(view.container);
  }

  it("its own animationend removes it", () => {
    const badge = emphasised();
    endEmphasis(badge);
    expect(badge).not.toHaveAttribute("data-emphasis");
  });

  it("an unrelated animationend does not", () => {
    const badge = emphasised();
    fireEvent.animationEnd(badge, { animationName: "ap-pulse" });
    fireEvent.animationEnd(badge, { animationName: "ap-rise-in" });
    expect(badge).toHaveAttribute("data-emphasis");
  });

  it("without animationend the leftover is inert: same text, icon and tone", () => {
    const plain = badgeOf(render(<StatusBadge post="published" />).container);
    const badge = emphasised();
    expect(badge).toHaveAttribute("data-emphasis");
    expect(badge.className).toBe(plain.className);
    expect(badge.innerHTML).toBe(plain.innerHTML);
  });

  it.each([
    ...(Object.keys(ACCOUNT_STATUS) as AccountHealthState[]).map(
      (account) => [{ account }] as const,
    ),
    ...(Object.keys(PLATFORM_STATUS) as PlatformStatus[]).map(
      (platform) => [{ platform }] as const,
    ),
  ])(
    "account and platform badges never get activity or emphasis: %o",
    (props) => {
      const { container } = render(<StatusBadge {...props} />);
      const badge = badgeOf(container);
      expect(badge).not.toHaveAttribute("data-activity");
      expect(badge).not.toHaveAttribute("data-emphasis");
      expect(container.querySelector(".ap-badge__activity")).toBeNull();
    },
  );
});

describe("Publishing activity", () => {
  it.each(POST_STATES)("%s", (state) => {
    const { container } = render(<StatusBadge post={state} />);
    const badge = badgeOf(container);
    const dot = container.querySelector(".ap-badge__activity");
    if (state === "publishing") {
      expect(badge).toHaveAttribute("data-activity");
      expect(dot).toHaveAttribute("aria-hidden", "true");
    } else {
      expect(badge).not.toHaveAttribute("data-activity");
      expect(dot).toBeNull();
    }
  });

  it("keeps the label and the clock icon, with no role, live region or focus", () => {
    const plain = render(<StatusBadge post="scheduled_manual" />).container;
    const { container } = render(<StatusBadge post="publishing" />);
    const badge = badgeOf(container);
    expect(badge).toHaveTextContent(/^Publishing$/);
    expect(badge.querySelector("svg")?.outerHTML).toBe(
      plain.querySelector("svg")?.outerHTML,
    );
    for (const element of [badge, ...badge.querySelectorAll("*")]) {
      expect(element).not.toHaveAttribute("role");
      expect(element).not.toHaveAttribute("aria-live");
      expect(element).not.toHaveAttribute("tabindex");
    }
    expect(document.activeElement).toBe(document.body);
  });

  it("the dot's own animation ending keeps the activity", () => {
    const { container } = render(<StatusBadge post="publishing" />);
    const dot = container.querySelector(".ap-badge__activity")!;
    fireEvent.animationEnd(dot, { animationName: "ap-pulse" });
    expect(badgeOf(container)).toHaveAttribute("data-activity");
    expect(container.querySelector(".ap-badge__activity")).not.toBeNull();
  });
});

describe("Publish Results", () => {
  function attempt(stage: PublicationAttempt["stage"]): PublicationAttempt {
    return { stage, platform: "youtube" } as PublicationAttempt;
  }

  function row(
    id: number,
    display_state: PostDisplayState,
    latest_attempt: PublicationAttempt | null = null,
  ): Publication {
    return {
      id,
      display_state,
      latest_attempt,
      account: {
        platform: "telegram",
        handle: `ch${id}`,
        display_name: null,
      },
    } as unknown as Publication;
  }

  function results(
    rows: Publication[],
    steps: Record<number, PostStep>,
    onEmphasisShown = vi.fn(),
  ) {
    const ui = (current: Publication[], currentSteps = steps) => (
      <MemoryRouter>
        <ResultsSection
          projectId={1}
          rows={current}
          steps={currentSteps}
          focus={false}
          onFocused={() => {}}
          onEmphasisShown={onEmphasisShown}
        />
      </MemoryRouter>
    );
    const view = render(ui(rows));
    return {
      onEmphasisShown,
      badges: () => [
        ...view.container.querySelectorAll<HTMLElement>(".ap-result .ap-badge"),
      ],
      aggregate: () =>
        view.container.querySelector(".ap-publish-results__aggregate"),
      show: (next: Publication[], nextSteps = steps) =>
        view.rerender(ui(next, nextSteps)),
      unmount: view.unmount,
    };
  }

  const done = (run: PostStep["run"] = "now"): PostStep => ({
    run,
    status: "done",
    message: null,
  });

  it("case 3: a Post of this action already Published is emphasised once", () => {
    const view = results([row(1, "published")], { 1: done() });
    const [badge] = view.badges();
    expect(badge).toHaveAttribute("data-emphasis");
    expect(view.onEmphasisShown).toHaveBeenCalledTimes(1);
    expect(view.onEmphasisShown).toHaveBeenCalledWith(1);

    endEmphasis(badge);
    expect(badge).not.toHaveAttribute("data-emphasis");
    // A poll with new objects and the same state does not repeat it.
    view.show([row(1, "published")], { 1: { ...done(), emphasized: true } });
    expect(view.badges()[0]).not.toHaveAttribute("data-emphasis");
    expect(view.onEmphasisShown).toHaveBeenCalledTimes(1);
  });

  it.each<[string, Record<number, PostStep>]>([
    ["already emphasised (remount)", { 1: { ...done(), emphasized: true } }],
    ["no steps (reload, or not in this action)", {}],
    ["a scheduled action", { 1: done("schedule") }],
    [
      "a start that failed",
      { 1: { run: "now", status: "error", message: "x" } },
    ],
    [
      "a start still running",
      { 1: { run: "now", status: "running", message: null } },
    ],
  ])("no fast-path when %s", (_, steps) => {
    const view = results([row(1, "published")], steps);
    expect(view.badges()[0]).not.toHaveAttribute("data-emphasis");
    expect(view.onEmphasisShown).not.toHaveBeenCalled();
  });

  it("a remount after emphasis_shown never repeats it", () => {
    const first = results([row(1, "published")], { 1: done() });
    expect(first.badges()[0]).toHaveAttribute("data-emphasis");
    first.unmount();
    const again = results([row(1, "published")], {
      1: { ...done(), emphasized: true },
    });
    expect(again.badges()[0]).not.toHaveAttribute("data-emphasis");
    expect(again.onEmphasisShown).not.toHaveBeenCalled();
  });

  it("an observed Publishing → Published also reports the emphasis", () => {
    const view = results([row(1, "publishing")], { 1: done() });
    expect(view.badges()[0]).not.toHaveAttribute("data-emphasis");
    view.show([row(1, "published")]);
    expect(view.badges()[0]).toHaveAttribute("data-emphasis");
    expect(view.onEmphasisShown).toHaveBeenCalledWith(1);
  });

  it("Publishing… and Processing share the activity; the aggregate is unchanged", () => {
    const view = results(
      [
        row(1, "publishing", attempt("uploading")),
        row(2, "publishing", attempt("processing")),
        row(3, "publishing", attempt("finalizing")),
        row(4, "failed"),
        row(5, "published"),
      ],
      {},
    );
    const badges = view.badges();
    expect(badges.map((badge) => badge.textContent)).toEqual([
      "Publishing…",
      "Processing",
      "Processing",
      "Failed",
      "Published",
    ]);
    expect(badges.map((badge) => badge.hasAttribute("data-activity"))).toEqual([
      true,
      true,
      true,
      false,
      false,
    ]);
    for (const badge of badges.slice(0, 3)) {
      expect(badge.querySelector(".ap-badge__activity")).toHaveAttribute(
        "aria-hidden",
        "true",
      );
    }
    expect(view.aggregate()).toHaveAttribute("aria-live", "polite");
    expect(view.aggregate()).toHaveTextContent(
      "1 published · 3 publishing · 1 failed",
    );
  });
});
