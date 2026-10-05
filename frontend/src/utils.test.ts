import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, parseHashtags } from "./utils.ts";

describe("formatBytes", () => {
  it("uses readable units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1500)).toBe("1.5 KB");
    expect(formatBytes(18_734_211)).toBe("18.7 MB");
    expect(formatBytes(2_000_000_000)).toBe("2.0 GB");
  });
});

describe("formatDuration", () => {
  it("formats minutes and hours", () => {
    expect(formatDuration(14.4)).toBe("0:14");
    expect(formatDuration(62)).toBe("1:02");
    expect(formatDuration(3725)).toBe("1:02:05");
  });

  it("shows a dash when unknown", () => {
    expect(formatDuration(null)).toBe("—");
  });
});

describe("parseHashtags", () => {
  it("splits on spaces and commas keeping order", () => {
    expect(parseHashtags(" #l4i4 summer,reels ,, ")).toEqual([
      "#l4i4",
      "summer",
      "reels",
    ]);
  });

  it("returns an empty list for blank text", () => {
    expect(parseHashtags("   ")).toEqual([]);
  });
});
