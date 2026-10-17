import { useEffect, useRef } from "react";

/**
 * Tells the parent when a panel's connection changes (connected, reconnect
 * needed, channel chosen…), so it can refresh account health. The first value
 * is the initial load and is not reported. The panel keeps its own logic.
 */
export function useConnectionSignal(
  signal: string | null,
  onChange: (() => void) | undefined,
): void {
  const previous = useRef<string | null>(null);
  useEffect(() => {
    if (signal === null) {
      return;
    }
    if (previous.current !== null && previous.current !== signal) {
      onChange?.();
    }
    previous.current = signal;
  }, [signal, onChange]);
}
