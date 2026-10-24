import { loopbackUrl } from "./host-only.ts";

/**
 * Shown instead of Connect/Reconnect: a phone or another computer can review,
 * schedule and publish, but connecting these accounts needs the host itself.
 * Only an indication: nothing navigates there from a remote device.
 */
function HostOnlyNotice({ platform }: { platform: "YouTube" | "TikTok" }) {
  return (
    <div className="muted ap-host-only" role="note">
      <p>
        Connect or reconnect {platform} from the computer that runs
        AutoPublisher.
      </p>
      <p>
        On that computer, open <code>{loopbackUrl()}</code>
      </p>
    </div>
  );
}

export default HostOnlyNotice;
