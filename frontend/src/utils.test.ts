import { afterEach, describe, expect, it, vi } from "vitest";
import {
  formatBytes,
  formatDuration,
  fromDateTimeLocalValue,
  isOverdue,
  parseHashtags,
  toDateTimeLocalValue,
} from "./utils.ts";

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

describe("datetime-local values", () => {
  it("round-trips a local value through an ISO instant", () => {
    const iso = fromDateTimeLocalValue("2100-03-15T18:45");
    expect(new Date(iso).getTime()).toBe(
      new Date(2100, 2, 15, 18, 45).getTime(),
    );
    expect(toDateTimeLocalValue(iso)).toBe("2100-03-15T18:45");
  });
});

describe("isOverdue", () => {
  it("is only the derived overdue condition of armed publications", () => {
    expect(isOverdue({ auto_publish_state: "overdue" })).toBe(true);
    for (const state of [
      "disabled",
      "waiting",
      "due",
      "paused",
      null,
    ] as const) {
      expect(isOverdue({ auto_publish_state: state })).toBe(false);
    }
  });
});

describe("local dates around daylight saving changes", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("converts local times to UTC instants in Europe/Madrid", () => {
    vi.stubEnv("TZ", "Europe/Madrid");

    // Normal summer and winter times.
    expect(fromDateTimeLocalValue("2026-10-24T18:00")).toBe(
      "2026-10-24T16:00:00.000Z",
    );
    expect(fromDateTimeLocalValue("2026-10-26T18:00")).toBe(
      "2026-10-26T17:00:00.000Z",
    );
    // 25 October: 02:30 happens twice; the first occurrence (+02:00) is used.
    expect(fromDateTimeLocalValue("2026-10-25T02:30")).toBe(
      "2026-10-25T00:30:00.000Z",
    );
    // 29 March: 02:30 does not exist; it becomes 03:30 (+02:00).
    expect(fromDateTimeLocalValue("2026-03-29T02:30")).toBe(
      "2026-03-29T01:30:00.000Z",
    );
    expect(toDateTimeLocalValue("2026-10-25T01:30:00Z")).toBe(
      "2026-10-25T02:30",
    );
  });
});
