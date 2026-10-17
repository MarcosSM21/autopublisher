import type { Account } from "../types.ts";
import InstagramConnectionPanel from "./InstagramConnectionPanel.tsx";
import TelegramConnectionPanel from "./TelegramConnectionPanel.tsx";
import ThreadsConnectionPanel from "./ThreadsConnectionPanel.tsx";
import TikTokConnectionPanel from "./TikTokConnectionPanel.tsx";
import YouTubeConnectionPanel from "./YouTubeConnectionPanel.tsx";

interface ConnectionPanelProps {
  account: Account;
  projectActive: boolean;
  /** Called when the connection changes (see useConnectionSignal). */
  onConnectionChange?: () => void;
}

/** The existing connection panel of the account's platform (none for X). */
function ConnectionPanel({
  account,
  projectActive,
  onConnectionChange,
}: ConnectionPanelProps) {
  const props = { account, projectActive, onConnectionChange };
  switch (account.platform) {
    case "youtube":
      return <YouTubeConnectionPanel {...props} />;
    case "instagram":
      return <InstagramConnectionPanel {...props} />;
    case "threads":
      return <ThreadsConnectionPanel {...props} />;
    case "tiktok":
      return <TikTokConnectionPanel {...props} />;
    case "telegram":
      return <TelegramConnectionPanel {...props} />;
    default:
      return null;
  }
}

export default ConnectionPanel;
