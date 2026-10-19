import PlatformDetails from "../../../components/platform/PlatformDetails.tsx";
import type { DeclarationControl } from "../../../components/platform/tiktok-declaration.ts";
import type { Publication } from "../../../types.ts";
import { cardId } from "../final-action.ts";

interface PlatformDetailsListProps {
  drafts: Publication[];
  /** The TikTok declaration of the task's action, per Post. */
  declaration: (postId: number) => DeclarationControl;
  /** Per-Post message of the last action (e.g. "Didn't start · …"). */
  messages: Record<number, string | null | undefined>;
}

/** One platform card per Draft; each saves on its own (autosave). */
function PlatformDetailsList({
  drafts,
  declaration,
  messages,
}: PlatformDetailsListProps) {
  return (
    <section
      className="ap-publish-section"
      aria-labelledby="publish-platform-title"
    >
      <h3 id="publish-platform-title" className="ap-publish-section__title">
        Platform details
      </h3>
      <ul className="ap-platform-list">
        {drafts.map((post) => (
          <li key={post.id}>
            {messages[post.id] && (
              <p className="ap-field__error">{messages[post.id]}</p>
            )}
            <PlatformDetails
              publication={post}
              id={cardId(post.id)}
              headingLevel={4}
              tiktokDeclaration={declaration(post.id)}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

export default PlatformDetailsList;
