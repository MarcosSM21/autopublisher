import { useEffect, useState } from "react";
import { ApiError } from "../api.ts";

/**
 * Whether the media or post in the URL is known not to belong to the project:
 * it does not exist (404) or it belongs to another project. Other errors are
 * left to the page, which shows them as it always did.
 */
export function useMissingFromProject(
  id: number | null,
  projectId: number,
  load: (id: number) => Promise<{ project_id: number }>,
): boolean {
  const [missing, setMissing] = useState<{ key: string; value: boolean }>();
  const key = `${projectId}:${id}`;

  useEffect(() => {
    if (id === null) {
      return;
    }
    let active = true;
    load(id)
      .then(
        (item) =>
          active && setMissing({ key, value: item.project_id !== projectId }),
      )
      .catch(
        (caught: unknown) =>
          active &&
          setMissing({
            key,
            value: caught instanceof ApiError && caught.status === 404,
          }),
      );
    return () => {
      active = false;
    };
  }, [id, projectId, load, key]);

  return missing?.key === key && missing.value;
}
