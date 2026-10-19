import type { PublishCheck } from "../../types.ts";
import { telegramChannel } from "./platform-state.ts";

interface TelegramDetailsProps {
  check: PublishCheck | null;
}

/**
 * Telegram has no per-Post options: the card only says where the post goes,
 * or that a channel must be chosen in the account first.
 */
function TelegramDetails({ check }: TelegramDetailsProps) {
  if (check === null) {
    return null;
  }
  const channel = telegramChannel(check);
  const noChannel = check.problems.some(
    (problem) => problem.code === "telegram_channel_required",
  );
  if (noChannel || channel === null) {
    // The card shows the "Choose a channel" link with its Blocked state.
    return <p>Choose the channel this account posts to in the account.</p>;
  }
  return <p>Posts to {channel}.</p>;
}

export default TelegramDetails;
