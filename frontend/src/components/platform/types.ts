import type { Publication } from "../../types.ts";
import type { AutosaveStatus } from "./useAutosave.ts";

/** What a platform form tells its card about its autosave. */
export interface AutosaveView {
  status: AutosaveStatus;
  error: string | null;
  retry: () => void;
}

/** Props every platform form receives from `PlatformDetails`. */
export interface PlatformFormProps {
  publication: Publication;
  /** Changes when the caption (description or hashtags) changes. */
  captionKey: string;
  /** Key of the form's autosave in the task's AutosaveRegistry. */
  registryKey: string;
  /** After each successful save (the card reads the publish check again). */
  onSaved: () => void;
  onAutosaveChange: (autosave: AutosaveView) => void;
}
