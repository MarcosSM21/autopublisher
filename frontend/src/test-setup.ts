import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { resetAuthSession } from "./shell/useAuthSession.ts";

// jsdom has no AnimationEvent: without it React listens to `webkitAnimationEnd`
// and `fireEvent.animationEnd` drops `animationName`. Defined before react-dom
// loads, so animation cleanup can be tested (Feature 026).
if (!("AnimationEvent" in window)) {
  class AnimationEventPolyfill extends Event {
    readonly animationName: string;
    readonly elapsedTime: number;
    readonly pseudoElement: string;

    constructor(type: string, init: AnimationEventInit = {}) {
      super(type, init);
      this.animationName = init.animationName ?? "";
      this.elapsedTime = init.elapsedTime ?? 0;
      this.pseudoElement = init.pseudoElement ?? "";
    }
  }
  Object.assign(window, { AnimationEvent: AnimationEventPolyfill });
}

// Each test starts with an unknown session, loaded again from its fake API.
afterEach(() => {
  resetAuthSession();
});
