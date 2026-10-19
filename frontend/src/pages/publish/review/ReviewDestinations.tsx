import { useState } from "react";
import { Link } from "react-router";
import type { Publication } from "../../../types.ts";
import Button from "../../../ui/Button.tsx";
import { Dialog } from "../../../ui/Dialog.tsx";
import Disclosure from "../../../ui/Disclosure.tsx";
import { accountName } from "../../../utils.ts";
import { DestinationStatusText } from "../compose/DestinationList.tsx";
import type { Destination } from "../destinations.ts";
import { DESTINATIONS_ID } from "../final-action.ts";

interface ReviewDestinationsProps {
  projectId: number;
  /** Drafts still to finish. */
  drafts: Publication[];
  /** Accounts already in the task (any state). */
  memberAccounts: number[];
  destinations: Destination[];
  onAdd: (destination: Destination) => Promise<string | null>;
  onRemove: (post: Publication) => Promise<string | null>;
  onAddToTask: (postId: number) => void;
}

/**
 * The task's destinations, folded into a summary: remove one (it is cancelled,
 * after a confirmation) or add another (a new Draft, or the one removed from
 * this task again). An account with a Draft of this Media outside the task
 * can join it without any write.
 */
function ReviewDestinations({
  projectId,
  drafts,
  memberAccounts,
  destinations,
  onAdd,
  onRemove,
  onAddToTask,
}: ReviewDestinationsProps) {
  const [removing, setRemoving] = useState<Publication | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<{
    accountId: number;
    text: string;
    postId?: number;
  } | null>(null);
  const others = destinations.filter(
    (destination) => !memberAccounts.includes(destination.accountId),
  );
  const names = drafts.map((post) => accountName(post.account)).join(", ");

  async function add(destination: Destination) {
    setBusy(destination.accountId);
    setMessage(null);
    const error = await onAdd(destination);
    setBusy(null);
    if (error !== null) {
      setMessage({
        accountId: destination.accountId,
        text: `${destination.name}: ${error}`,
      });
    }
  }

  async function remove(post: Publication) {
    setBusy(post.account_id);
    setMessage(null);
    const error = await onRemove(post);
    setBusy(null);
    setRemoving(null);
    if (error !== null) {
      setMessage({ accountId: post.account_id, text: error, postId: post.id });
    }
  }

  const notice = message && (
    <p className="ap-field__error" role="alert">
      {message.text}
      {message.postId !== undefined && (
        <>
          {" "}
          <Link
            className="ap-link"
            to={`/p/${projectId}/posts/${message.postId}`}
          >
            View post
          </Link>
        </>
      )}
    </p>
  );

  return (
    <section
      id={DESTINATIONS_ID}
      tabIndex={-1}
      className="ap-publish-section"
      aria-labelledby="publish-destinations-title"
    >
      <h3 id="publish-destinations-title" className="ap-publish-section__title">
        Destinations · {drafts.length}
      </h3>
      {names && <p className="ap-meta">{names}</p>}
      {notice}
      <Disclosure label="Change destinations">
        <div className="ap-review-destinations">
          {drafts.length > 0 && (
            <ul className="ap-destination-list" aria-label="In this task">
              {drafts.map((post) => (
                <li key={post.id} className="ap-destination">
                  <span className="ap-destination__name">
                    {accountName(post.account)}
                  </span>
                  <Button
                    variant="ghost"
                    aria-label={`Remove ${accountName(post.account)}`}
                    loading={busy === post.account_id}
                    onClick={() => setRemoving(post)}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {others.length > 0 && (
            <ul className="ap-destination-list" aria-label="Add a destination">
              {others.map((destination) => (
                <li
                  key={destination.accountId}
                  className={
                    destination.status.kind === "blocked"
                      ? "ap-destination ap-destination--unavailable"
                      : "ap-destination"
                  }
                >
                  <span className="ap-destination__name">
                    {destination.name}
                  </span>
                  {destination.status.kind === "available" ? (
                    <Button
                      aria-label={`Add ${destination.name}`}
                      loading={busy === destination.accountId}
                      onClick={() => void add(destination)}
                    >
                      Add
                    </Button>
                  ) : (
                    <DestinationStatusText
                      destination={destination}
                      onAddToTask={onAddToTask}
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Disclosure>
      {removing && (
        <Dialog
          open
          onOpenChange={(open) => !open && setRemoving(null)}
          title={`Remove ${accountName(removing.account)}?`}
          description="Its draft will be cancelled. You can add this destination again."
          footer={
            <>
              <Button
                variant="danger"
                loading={busy === removing.account_id}
                onClick={() => void remove(removing)}
              >
                Remove
              </Button>
              <Button onClick={() => setRemoving(null)}>Keep</Button>
            </>
          }
        >
          {null}
        </Dialog>
      )}
    </section>
  );
}

export default ReviewDestinations;
