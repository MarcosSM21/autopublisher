import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { toApiError } from "../../utils.ts";
import { AutosaveRegistryContext } from "./autosave-registry.ts";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

export interface Autosave<T> {
  status: AutosaveStatus;
  /** Safe message of the last failed save (status "error"). */
  error: string | null;
  /** Saves `value` now, or after the request in flight (latest value only). */
  schedule: (value: T) => void;
  /** Sends the last value again after a failure. */
  retry: () => void;
  /** Resolves when nothing is pending or in flight: false if the last save failed. */
  flush: () => Promise<boolean>;
}

interface AutosaveOptions<R> {
  /** Called with the response of the latest value only (never a stale one). */
  onSaved?: (result: R) => void;
  /**
   * Registers this autosave in the surrounding AutosaveRegistry under this key,
   * so the task can flush every card before its final action.
   */
  registryKey?: string;
}

/**
 * Autosave of one document (research R-04): at most one request in flight; a
 * value scheduled meanwhile waits and only the latest one is sent when the
 * flight settles. Ordering, not aborting, gives last-write-wins: a response
 * that arrives while a newer value is pending is ignored, so it never
 * overwrites a later edit.
 */
export function useAutosave<T, R>(
  save: (value: T) => Promise<R>,
  { onSaved, registryKey }: AutosaveOptions<R> = {},
): Autosave<T> {
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const saveRef = useRef(save);
  const onSavedRef = useRef(onSaved);
  const pending = useRef<{ value: T } | null>(null);
  const running = useRef<Promise<void> | null>(null);
  const lastValue = useRef<{ value: T } | null>(null);
  const failed = useRef(false);

  useEffect(() => {
    saveRef.current = save;
    onSavedRef.current = onSaved;
  });

  const run = useCallback(async () => {
    while (pending.current) {
      const { value } = pending.current;
      pending.current = null;
      lastValue.current = { value };
      setStatus("saving");
      try {
        const result = await saveRef.current(value);
        // A newer value is waiting: this response is already stale.
        if (pending.current === null) {
          failed.current = false;
          setError(null);
          setStatus("saved");
          onSavedRef.current?.(result);
        }
      } catch (caught) {
        if (pending.current === null) {
          failed.current = true;
          setError(toApiError(caught).message);
          setStatus("error");
        }
      }
    }
  }, []);

  const schedule = useCallback(
    (value: T) => {
      pending.current = { value };
      if (running.current === null) {
        running.current = run().finally(() => {
          running.current = null;
        });
      }
    },
    [run],
  );

  const retry = useCallback(() => {
    if (lastValue.current !== null) {
      schedule(lastValue.current.value);
    }
  }, [schedule]);

  const flush = useCallback(async () => {
    while (running.current !== null) {
      await running.current;
    }
    return !failed.current;
  }, []);

  // Only the registry's stable callbacks: its value changes with every report.
  const registry = useContext(AutosaveRegistryContext);
  const register = registry?.register;
  const report = registry?.report;
  useEffect(() => {
    if (register === undefined || registryKey === undefined) {
      return;
    }
    return register(registryKey, flush, retry);
  }, [register, registryKey, flush, retry]);
  useEffect(() => {
    if (report !== undefined && registryKey !== undefined) {
      report(registryKey, status === "error");
    }
  }, [report, registryKey, status]);

  return { status, error, schedule, retry, flush };
}
