import type { AssetPublication } from "../../types.ts";
import { POST_STATUS } from "../../ui/status.ts";
import { destinationLabel } from "./inheritance.ts";

/**
 * Inline note while editing: how many Posts this change also updates, where
 * they go and their state.
 */
function InheritanceWarning({ affected }: { affected: AssetPublication[] }) {
  return (
    <div className="ap-inheritance-warning" role="status">
      {affected.length > 0 && (
        <>
          <p>
            This change also updates {affected.length}{" "}
            {affected.length === 1 ? "post that uses" : "posts that use"} the
            media's text:
          </p>
          <ul>
            {affected.map((publication) => (
              <li key={publication.publication_id}>
                {destinationLabel(publication)} ·{" "}
                {POST_STATUS[publication.display_state].label}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default InheritanceWarning;
