import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError } from "../../utils.ts";
import type { PlatformFormProps } from "./types.ts";
import { useAutosave } from "./useAutosave.ts";

interface PlatformOptionsConfig<O, W> extends PlatformFormProps {
  /** Module-level functions (stable): the API read and full-document write. */
  load: (publicationId: number) => Promise<O>;
  save: (publicationId: number, values: W) => Promise<O>;
  /** The writable document of the options, sent whole on every save. */
  toWrite: (options: O) => W;
  /** Rules applied to the document before it is sent (optional). */
  normalize?: (values: W) => W;
}

/**
 * The options of one Post for a platform card: read once on mount (and when
 * the caption changes), then every change is sent as the full document
 * through `useAutosave`. Only the response of the latest value replaces the
 * local options.
 */
export function usePlatformOptions<O, W>({
  publication,
  captionKey,
  registryKey,
  onSaved,
  onAutosaveChange,
  load,
  save,
  toWrite,
  normalize,
}: PlatformOptionsConfig<O, W>) {
  const [options, setOptions] = useState<O | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const latest = useRef<W | null>(null);

  useEffect(() => {
    let active = true;
    load(publication.id)
      .then((loaded) => {
        if (active) {
          latest.current = toWrite(loaded);
          setOptions(loaded);
          setLoadError(null);
        }
      })
      .catch(
        (caught: unknown) => active && setLoadError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [publication.id, captionKey, load, toWrite]);

  const autosave = useAutosave((values: W) => save(publication.id, values), {
    registryKey,
    onSaved: (result) => {
      latest.current = toWrite(result);
      setOptions(result);
      onSaved();
    },
  });
  const { status, error, retry, schedule } = autosave;
  useEffect(() => {
    onAutosaveChange({ status, error, retry });
  }, [status, error, retry, onAutosaveChange]);

  /** Applies a change locally at once and saves the whole document. */
  const change = useCallback(
    (values: Partial<W>) => {
      if (latest.current === null) {
        return;
      }
      const merged = { ...latest.current, ...values };
      const next = normalize ? normalize(merged) : merged;
      latest.current = next;
      setOptions((current) => (current ? { ...current, ...next } : current));
      schedule(next);
    },
    [normalize, schedule],
  );

  return { options, loadError, change };
}
