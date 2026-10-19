import { describe, expect, it } from "vitest";
import type { PostDisplayState, Publication } from "../../types.ts";
import {
  MAX_SET_SIZE,
  parsePostsParam,
  partition,
  serializePostsParam,
  validateMembers,
} from "./publish-set.ts";

function post(
  id: number,
  values: Partial<Pick<Publication, "project_id" | "content_id">> & {
    display_state?: PostDisplayState;
  } = {},
): Publication {
  return {
    id,
    project_id: 1,
    content_id: 10,
    display_state: "draft",
    ...values,
  } as Publication;
}

describe("parsePostsParam", () => {
  it.each([
    [null, []],
    ["", []],
    ["12,13,14", [12, 13, 14]],
    ["14,12,13", [14, 12, 13]],
    ["12,13,12,14,13", [12, 13, 14]],
    ["12,abc,0,-3,1.5,13", [12, 13]],
    [" 12 , 13 ", [12, 13]],
    ["99999999999999999999,7", [7]],
  ])("%j → %j", (value, expected) => {
    expect(parsePostsParam(value)).toEqual(expected);
  });

  it(`keeps at most ${MAX_SET_SIZE} ids`, () => {
    const many = Array.from({ length: 60 }, (_, index) => index + 1);
    expect(parsePostsParam(many.join(","))).toEqual(
      many.slice(0, MAX_SET_SIZE),
    );
  });

  it("serializes in order", () => {
    expect(serializePostsParam([14, 12])).toBe("14,12");
  });
});

describe("validateMembers", () => {
  const media = { projectId: 1, mode: "media" as const, mediaId: 10 };

  it.each([
    ["the same project and Media", post(1), true],
    ["another project", post(2, { project_id: 9 }), false],
    ["another Media", post(3, { content_id: 11 }), false],
    ["a text post in media mode", post(4, { content_id: null }), false],
  ])("%s → member: %s", (_, candidate, member) => {
    const { members, dropped } = validateMembers([candidate], media);
    expect(members.map((item) => item.id)).toEqual(
      member ? [candidate.id] : [],
    );
    expect(dropped).toEqual(member ? [] : [candidate.id]);
  });

  it("a text task keeps only Posts without Media", () => {
    const { members } = validateMembers(
      [post(1), post(2, { content_id: null })],
      {
        projectId: 1,
        mode: "text",
        mediaId: null,
      },
    );
    expect(members.map((item) => item.id)).toEqual([2]);
  });
});

it("partitions a mixed set by display state, keeping the set order", () => {
  const states: PostDisplayState[] = [
    "scheduled_automatic",
    "draft",
    "publishing",
    "published",
    "failed",
    "draft",
    "needs_review",
    "needs_action",
  ];
  const { review, results } = partition(
    states.map((state, index) => post(index + 1, { display_state: state })),
  );
  expect(review.map((item) => item.id)).toEqual([2, 6]);
  expect(results.map((item) => item.id)).toEqual([1, 3, 4, 5, 7, 8]);
});
