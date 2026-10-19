// The Publish set (contracts/ui.md §2, data-model §4): the ordered ids of the
// Posts of one Publish task, kept in `?posts=`. The URL is its only source: it
// is never inferred from the Media's history.
import type { Publication } from "../../types.ts";
import { parseId } from "../../route-params.ts";

/** At most this many ids are read from the URL; the rest are dropped. */
export const MAX_SET_SIZE = 50;

export type PublishMode = "media" | "text";

export interface SetScope {
  projectId: number;
  mode: PublishMode;
  /** The Media of the task (media mode only). */
  mediaId: number | null;
}

/**
 * `?posts=` → ids: positive integers only, order kept, first occurrence wins,
 * at most MAX_SET_SIZE. Anything else in the list is ignored.
 */
export function parsePostsParam(value: string | null): number[] {
  if (value === null) {
    return [];
  }
  const ids: number[] = [];
  for (const part of value.split(",")) {
    const id = parseId(part.trim());
    if (id !== null && !ids.includes(id)) {
      ids.push(id);
      if (ids.length === MAX_SET_SIZE) {
        break;
      }
    }
  }
  return ids;
}

export function serializePostsParam(ids: readonly number[]): string {
  return ids.join(",");
}

/** A loaded Post belongs to the set of this task. */
export function isMember(post: Publication, scope: SetScope): boolean {
  if (post.project_id !== scope.projectId) {
    return false;
  }
  return scope.mode === "media"
    ? post.content_id !== null && post.content_id === scope.mediaId
    : post.content_id === null;
}

/**
 * Keeps the Posts that belong to the task (same project; the task's Media, or
 * no Media for a text task), in their order, and names the others.
 */
export function validateMembers(
  posts: readonly Publication[],
  scope: SetScope,
): { members: Publication[]; dropped: number[] } {
  const members: Publication[] = [];
  const dropped: number[] = [];
  for (const post of posts) {
    if (isMember(post, scope)) {
      members.push(post);
    } else {
      dropped.push(post.id);
    }
  }
  return { members, dropped };
}

export interface Partition {
  /** Drafts still to finish (Review). */
  review: Publication[];
  /** Posts that already left Draft (Results). */
  results: Publication[];
}

/** By the backend's display state only: Draft → Review, anything else → Results. */
export function partition(members: readonly Publication[]): Partition {
  return {
    review: members.filter((post) => post.display_state === "draft"),
    results: members.filter((post) => post.display_state !== "draft"),
  };
}

export function withId(ids: readonly number[], id: number): number[] {
  return ids.includes(id) ? [...ids] : [...ids, id];
}

export function withoutId(ids: readonly number[], id: number): number[] {
  return ids.filter((value) => value !== id);
}
