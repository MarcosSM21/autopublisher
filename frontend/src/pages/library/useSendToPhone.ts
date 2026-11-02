import { useState } from "react";
import { sendToPhone } from "../../api.ts";
import { toApiError } from "../../utils.ts";

/**
 * Send one Media to the configured phone through the existing endpoint. The
 * transfer runs inside the request, so `sending` lasts until it ends.
 */
export function useSendToPhone(contentId: number) {
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setSending(true);
    setSent(false);
    setError(null);
    try {
      await sendToPhone(contentId);
      setSent(true);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setSending(false);
    }
  }

  return { sending, sent, error, send };
}
