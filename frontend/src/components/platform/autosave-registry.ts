import { createContext, useContext } from "react";

export interface AutosaveRegistryValue {
  /** Adds a card's flush (and retry); returns the function that removes it. */
  register: (
    key: string,
    flush: () => Promise<boolean>,
    retry?: () => void,
  ) => () => void;
  /** A card tells whether its last save failed. */
  report: (key: string, failed: boolean) => void;
  /** Waits for every registered card: false if any save failed. */
  flushAll: () => Promise<boolean>;
  /** Keys whose last save failed, read now (safe after an await). */
  failedKeys: () => string[];
  /** Sends the failed saves again and waits for every card. */
  retryFailed: () => Promise<boolean>;
  /** Cards whose last save failed. */
  errorCount: number;
  hasErrors: boolean;
}

export const AutosaveRegistryContext =
  createContext<AutosaveRegistryValue | null>(null);

/** The registry of the surrounding task (Publish, Post detail), if any. */
export function useAutosaveRegistry(): AutosaveRegistryValue | null {
  return useContext(AutosaveRegistryContext);
}
