import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AutosaveRegistryContext,
  type AutosaveRegistryValue,
} from "./autosave-registry.ts";

/**
 * Keeps the autosaves of the platform cards of one task, so its final action
 * (and Finish later) can wait for all of them and know whether any failed.
 * It only coordinates: every card still owns its own save.
 */
function AutosaveRegistry({ children }: { children: ReactNode }) {
  const flushes = useRef(new Map<string, () => Promise<boolean>>());
  const retries = useRef(new Map<string, () => void>());
  const [failed, setFailed] = useState<ReadonlySet<string>>(new Set());
  // The same set, readable right after an await (state would be stale there).
  const failedNow = useRef(new Set<string>());

  const report = useCallback((key: string, hasFailed: boolean) => {
    if (hasFailed) {
      failedNow.current.add(key);
    } else {
      failedNow.current.delete(key);
    }
    setFailed((current) => {
      if (current.has(key) === hasFailed) {
        return current;
      }
      const next = new Set(current);
      if (hasFailed) {
        next.add(key);
      } else {
        next.delete(key);
      }
      return next;
    });
  }, []);

  const register = useCallback(
    (key: string, flush: () => Promise<boolean>, retry?: () => void) => {
      flushes.current.set(key, flush);
      if (retry) {
        retries.current.set(key, retry);
      }
      return () => {
        if (flushes.current.get(key) === flush) {
          flushes.current.delete(key);
          retries.current.delete(key);
        }
        report(key, false);
      };
    },
    [report],
  );

  const flushAll = useCallback(async () => {
    const results = await Promise.all(
      [...flushes.current.values()].map((flush) => flush()),
    );
    return results.every(Boolean);
  }, []);

  const failedKeys = useCallback(() => [...failedNow.current], []);

  const retryFailed = useCallback(async () => {
    for (const key of failedNow.current) {
      retries.current.get(key)?.();
    }
    return flushAll();
  }, [flushAll]);

  const value = useMemo<AutosaveRegistryValue>(
    () => ({
      register,
      report,
      flushAll,
      failedKeys,
      retryFailed,
      errorCount: failed.size,
      hasErrors: failed.size > 0,
    }),
    [register, report, flushAll, failedKeys, retryFailed, failed],
  );

  return (
    <AutosaveRegistryContext.Provider value={value}>
      {children}
    </AutosaveRegistryContext.Provider>
  );
}

export default AutosaveRegistry;
