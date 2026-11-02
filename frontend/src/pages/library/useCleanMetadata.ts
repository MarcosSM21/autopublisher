import { useState } from "react";
import { removeMetadata } from "../../api.ts";
import { toApiError } from "../../utils.ts";

/**
 * Clean metadata of one Media through the existing endpoint, then reload with
 * `onChanged`: the new state is only shown once the backend has answered.
 */
export function useCleanMetadata(
  contentId: number,
  onChanged: () => Promise<void> | void,
) {
  const [cleaning, setCleaning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function clean() {
    setCleaning(true);
    setError(null);
    try {
      await removeMetadata(contentId);
      await onChanged();
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setCleaning(false);
    }
  }

  return { cleaning, error, clean };
}
