// Motion policy contract (Feature 026 T002/T003, contracts/ui.md §1): bounded
// motion, the emphasis token, the Auth-only glow, the touch hover guard and
// the favicon. jsdom runs no CSS, so these read the stylesheets as text.
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Vitest empties CSS modules (even `?raw`): the glob only lists the files.
const stylesheets = Object.fromEntries(
  Object.keys(import.meta.glob("../**/*.css")).map((path) => [
    path,
    readFileSync(new URL(path, import.meta.url), "utf8"),
  ]),
);

const publicFiles = import.meta.glob<string>(
  ["../../index.html", "../../public/favicon.svg"],
  { query: "?raw", import: "default", eager: true },
);

const FINE_HOVER = "@media (hover: hover) and (pointer: fine)";
const REDUCED_MOTION = "@media (prefers-reduced-motion: reduce)";

interface Rule {
  selectors: string[];
  /** Enclosing at-rule preludes, outermost first. */
  at: string[];
  body: string;
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** A minimal block parser: enough for our flat, hand-written stylesheets. */
function parseRules(css: string): Rule[] {
  const source = stripComments(css);
  const rules: Rule[] = [];
  const stack: { prelude: string; start: number }[] = [];
  let segmentStart = 0;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (char === "{") {
      stack.push({
        prelude: source.slice(segmentStart, i).trim().replace(/\s+/g, " "),
        start: i + 1,
      });
      segmentStart = i + 1;
    } else if (char === "}") {
      const open = stack.pop();
      if (open && !open.prelude.startsWith("@")) {
        rules.push({
          selectors: open.prelude.split(",").map((s) => s.trim()),
          at: stack.map((entry) => entry.prelude),
          body: source.slice(open.start, i),
        });
      }
      segmentStart = i + 1;
    } else if (char === ";") {
      segmentStart = i + 1;
    }
  }
  return rules;
}

function sheet(path: string): string {
  const css = stylesheets[path];
  expect(css, path).toBeDefined();
  return css;
}

function allRules(): Rule[] {
  return Object.values(stylesheets).flatMap(parseRules);
}

function liftRules(selector: string): Rule[] {
  return allRules().filter(
    (rule) =>
      rule.selectors.includes(selector) && /\btranslate\s*:/.test(rule.body),
  );
}

describe("motion policy", () => {
  it("keeps the spinner as the only infinite animation", () => {
    const infinite = allRules().filter((rule) =>
      /\binfinite\b/.test(rule.body),
    );
    expect(infinite.map((rule) => rule.selectors)).toEqual([[".ap-spinner"]]);
    expect(infinite[0].body).toMatch(/animation:\s*ap-spin\b/);
  });

  it("defines the emphasis token and neutralises it with reduced motion", () => {
    const tokens = parseRules(sheet("./tokens.css"));
    const root = tokens.find(
      (rule) => rule.selectors.includes(":root") && rule.at.length === 0,
    );
    expect(root?.body).toMatch(/--motion-emphasis:\s*360ms\s*;/);

    const reduced = tokens.filter((rule) => rule.at.includes(REDUCED_MOTION));
    const reducedRoot = reduced.find((rule) =>
      rule.selectors.includes(":root"),
    );
    expect(reducedRoot?.body).toMatch(/--motion-emphasis:\s*0ms\s*;/);

    const everything = reduced.find((rule) => rule.selectors.includes("*"));
    expect(everything?.body).toMatch(
      /animation-duration:\s*0\.01ms\s*!important/,
    );
    expect(everything?.body).toMatch(
      /animation-iteration-count:\s*1\s*!important/,
    );
  });

  it.each([
    [".ap-media-card[data-just-imported]", "../pages/library/library.css"],
    [".ap-calendar-item[data-just-rescheduled]", "../pages/posts/posts.css"],
  ])(
    "%s runs ap-highlight once, from the emphasis token, ending at its natural style",
    (selector, path) => {
      const rules = parseRules(sheet(path)).filter((rule) =>
        rule.selectors.includes(selector),
      );
      expect(rules).toHaveLength(1);
      expect(rules[0].at).toEqual([]);
      expect(rules[0].body).toMatch(
        /animation:\s*ap-highlight\s+calc\(var\(--motion-emphasis\)\s*\*\s*4\)/,
      );
      expect(rules[0].body).not.toMatch(/forwards|both|infinite/);

      const keyframes = parseRules(sheet("./ui.css")).filter((rule) =>
        rule.at.includes("@keyframes ap-highlight"),
      );
      expect(keyframes.map((rule) => rule.selectors)).toEqual([["from"]]);
    },
  );

  it("uses a gradient only on the sign-in surfaces", () => {
    const withGradient = Object.entries(stylesheets)
      .filter(([, css]) => /gradient\(/.test(stripComments(css)))
      .map(([path]) => path);
    expect(withGradient).toEqual(["../pages/login/login.css"]);

    const glow = parseRules(sheet("../pages/login/login.css")).filter((rule) =>
      /gradient\(/.test(rule.body),
    );
    for (const rule of glow) {
      expect(rule.selectors.sort()).toEqual([".ap-auth-loading", ".ap-login"]);
      expect(rule.body).not.toMatch(/\banimation\b/);
    }
  });

  it.each([".ap-media-card:hover", ".ap-home-tile:hover"])(
    "lifts %s only with a fine pointer that can hover",
    (selector) => {
      const lifts = liftRules(selector);
      expect(lifts.length).toBeGreaterThan(0);
      for (const rule of lifts) {
        expect(rule.at).toContain(FINE_HOVER);
      }
    },
  );

  it("keeps the keyboard focus lift on every device", () => {
    const lifts = liftRules(".ap-media-card:focus-visible");
    expect(lifts.length).toBeGreaterThan(0);
    expect(lifts.some((rule) => rule.at.length === 0)).toBe(true);
  });
});

describe("favicon", () => {
  it("is linked from index.html as one SVG", () => {
    const html = publicFiles["../../index.html"];
    expect(html).toContain(
      '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />',
    );
    expect(html.match(/rel="icon"/g)).toHaveLength(1);
  });

  it("is the monogram, in its colours", () => {
    const svg = publicFiles["../../public/favicon.svg"];
    expect(svg).toBeDefined();
    expect(svg).toContain('viewBox="0 0 32 32"');
    expect(svg).toContain("#42634e");
    expect(svg).toContain("#f6f5f1");
  });
});
