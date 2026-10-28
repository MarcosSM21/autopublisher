import type {
  AccountHealthState,
  PlatformStatus,
  PostDisplayState,
} from "../types.ts";
import Badge from "./Badge.tsx";
import { ACCOUNT_STATUS, PLATFORM_STATUS, POST_STATUS } from "./status.ts";
import { usePublishedEmphasis } from "./usePublishedEmphasis.ts";

type StatusBadgeProps =
  | { post: PostDisplayState }
  | { account: AccountHealthState }
  | { platform: PlatformStatus };

/**
 * The state of a post, an account or a platform: text, icon and tone. A post
 * that is publishing shows the activity dot, and one seen reaching Published
 * the one-time emphasis; accounts and platforms never do.
 */
function StatusBadge(props: StatusBadgeProps) {
  const post = "post" in props ? props.post : null;
  const { emphasis, onEmphasisEnd } = usePublishedEmphasis(post);
  const appearance =
    "post" in props
      ? POST_STATUS[props.post]
      : "account" in props
        ? ACCOUNT_STATUS[props.account]
        : PLATFORM_STATUS[props.platform];
  return (
    <Badge
      tone={appearance.tone}
      icon={appearance.icon}
      activity={post === "publishing"}
      emphasis={emphasis}
      onEmphasisEnd={onEmphasisEnd}
    >
      {appearance.label}
    </Badge>
  );
}

export default StatusBadge;
