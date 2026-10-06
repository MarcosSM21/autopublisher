import { describe, expect, it } from "vitest";
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
  const now = new Date("2026-10-06T12:00:00Z");

  it("is true only for scheduled publications in the past", () => {
    expect(
      isOverdue(
        { status: "scheduled", scheduled_at: "2026-10-06T11:59:00Z" },
        now,
      ),
    ).toBe(true);
    expect(
      isOverdue(
        { status: "scheduled", scheduled_at: "2026-10-06T12:01:00Z" },
        now,
      ),
    ).toBe(false);
  });

  it("is false for unscheduled and cancelled publications", () => {
    expect(isOverdue({ status: "unscheduled", scheduled_at: null }, now)).toBe(
      false,
    );
    expect(
      isOverdue(
        { status: "cancelled", scheduled_at: "2000-01-01T10:00:00Z" },
        now,
      ),
    ).toBe(false);
  });
});
