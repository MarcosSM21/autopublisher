import type { AttentionTarget } from "../../types.ts";

/** Route of an attention action, exactly as the overview names it. */
export function targetPath(target: AttentionTarget): string {
  switch (target.type) {
    case "post":
      return `/p/${target.project_id}/posts/${target.id}`;
    case "account":
      return `/p/${target.project_id}/accounts/${target.id}`;
    case "settings":
      return "/settings";
  }
}
