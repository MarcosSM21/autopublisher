import { useCallback, useEffect, useState } from "react";
import { getPublication } from "../api.ts";
import type { Publication } from "../types.ts";
import {
  AUTOMATION_POLL_INTERVAL_MS,
  awaitsAutomaticStart,
  POLL_INTERVAL_MS,
} from "../utils.ts";

/**
 * A local copy of the publication, refreshed while an upload runs or while it
 * waits for the scheduler; `onChanged` is told when its status changes.
 */
export function useLivePublication(
  initial: Publication,
  onChanged: () => unknown,
) {
  // Kept locally so it can be refreshed while an upload runs.
  const [publication, setPublication] = useState(initial);
  // A reloaded queue (e.g. after editing the text) replaces the local copy.
  const [received, setReceived] = useState(initial);
  if (initial !== received) {
    setReceived(initial);
    setPublication(initial);
  }
  const publishing = publication.status === "publishing";
  // Uploads are followed closely; armed publications are reloaded so that a start
  // by the scheduler shows up without a manual reload.
  const pollInterval = publishing
    ? POLL_INTERVAL_MS
    : awaitsAutomaticStart(publication)
      ? AUTOMATION_POLL_INTERVAL_MS
      : null;
  const status = publication.status;

  useEffect(() => {
    if (pollInterval === null) {
      return;
    }
    const timer = window.setInterval(() => {
      getPublication(publication.id)
        .then((loaded) => {
          setPublication(loaded);
          if (loaded.status !== status) {
            void onChanged();
          }
        })
        .catch(() => {
          // A failed poll is retried on the next tick.
        });
    }, pollInterval);
    return () => window.clearInterval(timer);
  }, [pollInterval, status, publication.id, onChanged]);

  const handleReconciled = useCallback(
    (result: Publication) => {
      setPublication(result);
      void onChanged();
    },
    [onChanged],
  );

  return { publication, setPublication, handleReconciled };
}
