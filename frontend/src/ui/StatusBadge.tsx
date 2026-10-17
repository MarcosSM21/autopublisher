import type {
  AccountHealthState,
  PlatformStatus,
  PostDisplayState,
} from "../types.ts";
import Badge from "./Badge.tsx";
import { ACCOUNT_STATUS, PLATFORM_STATUS, POST_STATUS } from "./status.ts";

type StatusBadgeProps =
  | { post: PostDisplayState }
  | { account: AccountHealthState }
  | { platform: PlatformStatus };

/** The state of a post, an account or a platform: text, icon and tone. */
function StatusBadge(props: StatusBadgeProps) {
  const appearance =
    "post" in props
      ? POST_STATUS[props.post]
      : "account" in props
        ? ACCOUNT_STATUS[props.account]
        : PLATFORM_STATUS[props.platform];
  return (
    <Badge tone={appearance.tone} icon={appearance.icon}>
      {appearance.label}
    </Badge>
  );
}

export default StatusBadge;
