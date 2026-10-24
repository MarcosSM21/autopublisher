import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import {
  cancelPublication,
  checkPublicationStatus,
  deleteObject,
  getDeletionPreview,
  reactivatePublication,
} from "../../api.ts";
import DeleteConfirmDialog from "../../components/DeleteConfirmDialog.tsx";
import MediaPreview from "../../components/MediaPreview.tsx";
import AutosaveRegistry from "../../components/platform/AutosaveRegistry.tsx";
import PlatformDetails from "../../components/platform/PlatformDetails.tsx";
import type { FlashState } from "../../shell/Flash.tsx";
import type { Project, Publication } from "../../types.ts";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import DetailSurface from "../../ui/DetailSurface.tsx";
import { Dialog } from "../../ui/Dialog.tsx";
import Icon from "../../ui/Icon.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { accountName, publicationTitle, toApiError } from "../../utils.ts";
import { focusTarget } from "../publish/focus.ts";
import ActionDialog, { type DialogAction } from "./ActionDialog.tsx";
import Activity from "./Activity.tsx";
import CheckResultDialog from "./CheckResultDialog.tsx";
import { postActions, type PostAction } from "./post-actions.ts";
import PostContent from "./PostContent.tsx";
import PostWhen from "./PostWhen.tsx";
import type { Readiness } from "./readiness.ts";
import StatusActionPanel, { ActionButton } from "./StatusActionPanel.tsx";

/** States whose platform options can still change (the card is live). */
const LIVE: Publication["display_state"][] = [
  "draft",
  "scheduled_automatic",
  "scheduled_manual",
  "scheduled_paused",
  "missed",
  "failed",
];
/** States that can be cancelled (backend rules: not running, done or waiting). */
const CANCELLABLE: Publication["display_state"][] = [...LIVE, "needs_review"];
const DIALOG_ACTIONS: PostAction[] = [
  "publish_now",
  "retry_now",
  "reschedule",
  "edit_schedule",
  "publish_automatically",
  "move_to_drafts",
];

interface PostDetailProps {
  post: Publication;
  project: Project;
  readiness: Readiness | null;
  paused: boolean;
  /** Every Post of the project (from the same list). */
  posts: readonly Publication[];
  parentPath: string;
  panelFrom: "lg" | "never";
  /** After a change: the list is read again (it owns the Post). */
  onChanged: () => void;
}

/**
 * Post detail (plan §15): header, state and actions, When, Content, Platform
 * details, Activity and the destructive area. It reads the Post from the list,
 * so a change of state updates it in place (keyed by id only).
 */
function PostDetail({
  post: listed,
  project,
  readiness,
  paused,
  posts,
  parentPath,
  panelFrom,
  onChanged,
}: PostDetailProps) {
  const navigate = useNavigate();
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  // The answer of an action shows at once; the list catches up on reload.
  const [latest, setLatest] = useState<Publication | null>(null);
  const post =
    latest !== null && latest.updated_at >= listed.updated_at ? latest : listed;
  const [dialog, setDialog] = useState<DialogAction | "check_result" | null>(
    null,
  );
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState<PostAction | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [openDetails, setOpenDetails] = useState(0);
  const cardId = `post-platform-${post.id}`;
  const deleteReasonId = `post-delete-reason-${post.id}`;
  const plan = postActions(post, readiness, paused);

  useEffect(() => {
    if (openDetails > 0) {
      focusTarget(cardId);
    }
  }, [openDetails, cardId]);

  function changed(next: Publication) {
    setLatest(next);
    setDialog(null);
    onChanged();
  }

  async function run(action: PostAction | "cancel") {
    setBusy(action);
    setError(null);
    setMessage(null);
    try {
      if (action === "check_status") {
        const checked = await checkPublicationStatus(post.id);
        setMessage(checked.message);
        changed(checked.publication);
      } else {
        changed(
          await (action === "cancel"
            ? cancelPublication(post.id)
            : reactivatePublication(post.id)),
        );
      }
      setConfirmCancel(false);
    } catch (caught) {
      setError(toApiError(caught).message);
    } finally {
      setBusy(null);
    }
  }

  function onAction(action: PostAction) {
    if (DIALOG_ACTIONS.includes(action)) {
      setDialog(action as DialogAction);
    } else if (action === "check_result") {
      setDialog("check_result");
    } else if (action === "continue_publish" && post.content_id !== null) {
      void navigate(`/p/${project.id}/library/${post.content_id}/publish`);
    } else if (action === "continue_setup") {
      void navigate(`/p/${project.id}/posts/new?posts=${post.id}`);
    } else if (action === "complete_details") {
      setOpenDetails((value) => value + 1);
    } else if (action === "reactivate" || action === "check_status") {
      void run(action);
    }
  }

  // A TikTok inbox delivery offers its own Check status, next to what it checks.
  const inboxCheck =
    plan.primary === "check_status" && post.account.platform === "tiktok";
  const footer =
    !isMedium && plan.primary && !inboxCheck ? (
      <ActionButton
        action={plan.primary}
        post={post}
        variant="primary"
        busy={busy === plan.primary}
        onAction={onAction}
      />
    ) : undefined;
  const live = LIVE.includes(post.display_state);
  // Visual only: the backend's preview and DELETE stay the authority.
  const publishing = post.display_state === "publishing";

  function deleted() {
    setDeleting(false);
    onChanged();
    const state: FlashState = { flash: "Post deleted." };
    void navigate(parentPath, { state });
  }

  return (
    <DetailSurface
      title={publicationTitle(post)}
      parentPath={parentPath}
      panelFrom={panelFrom}
      sectionTitle="Posts"
      actions={footer}
    >
      <div className="ap-post-detail" aria-label="Post details" role="region">
        <header className="ap-post-detail__header">
          <span className="ap-post-detail__thumb" aria-hidden="true">
            {post.content ? (
              <MediaPreview content={post.content} />
            ) : (
              <Icon name="posts" />
            )}
          </span>
          <p className="ap-post-detail__where">
            {post.content ? "Media post" : "Text post"} ·{" "}
            {accountName(post.account)}
          </p>
        </header>
        <StatusActionPanel
          post={post}
          plan={plan}
          onAction={onAction}
          busy={busy === "cancel" ? null : busy}
          primaryElsewhere={footer !== undefined}
          onPostChanged={changed}
        />
        {error && (
          <p className="ap-field__error" role="alert">
            {error}
          </p>
        )}
        {message && <p role="status">{message}</p>}
        <PostWhen post={post} />
        <PostContent post={post} onChanged={changed} />
        <section
          className="ap-post-detail__section"
          aria-labelledby="post-platform"
        >
          <h3 id="post-platform" className="ap-post-detail__title">
            Platform details
          </h3>
          <AutosaveRegistry>
            <PlatformDetails
              publication={post}
              id={cardId}
              headingLevel={4}
              history={!live}
              showDeclaration={false}
              openRequest={openDetails}
            />
          </AutosaveRegistry>
        </section>
        <Activity post={post} />
        <section
          className="ap-post-detail__section ap-post-detail__danger"
          aria-label="Cancel or delete post"
        >
          <div className="ap-post-detail__row">
            {CANCELLABLE.includes(post.display_state) && (
              <Button
                className="ap-post-detail__cancel"
                onClick={() => setConfirmCancel(true)}
              >
                Cancel post
              </Button>
            )}
            <Button
              className="ap-delete-entry"
              disabled={publishing}
              aria-describedby={publishing ? deleteReasonId : undefined}
              onClick={() => setDeleting(true)}
            >
              Delete post
            </Button>
          </div>
          {publishing && (
            <p id={deleteReasonId} className="ap-meta">
              This post is being published right now.
            </p>
          )}
        </section>
      </div>
      {dialog === "check_result" && (
        <CheckResultDialog
          post={post}
          onClose={() => setDialog(null)}
          onDone={changed}
        />
      )}
      {dialog !== null && dialog !== "check_result" && (
        <ActionDialog
          action={dialog}
          post={post}
          posts={posts}
          paused={paused}
          onClose={() => setDialog(null)}
          onDone={changed}
        />
      )}
      {deleting && (
        <DeleteConfirmDialog
          title="Delete post?"
          loadPreview={() => getDeletionPreview("post", post.id)}
          remove={(confirmation) => deleteObject("post", post.id, confirmation)}
          onDeleted={deleted}
          onClose={() => setDeleting(false)}
        />
      )}
      {confirmCancel && (
        <Dialog
          open
          onOpenChange={(open) => !open && setConfirmCancel(false)}
          title="Cancel this post?"
          description="It won't be published. You can reactivate it later."
          footer={
            <>
              <Button
                variant="danger"
                loading={busy === "cancel"}
                onClick={() => void run("cancel")}
              >
                Cancel post
              </Button>
              <Button onClick={() => setConfirmCancel(false)}>Keep it</Button>
            </>
          }
        >
          {error && (
            <p className="ap-field__error" role="alert">
              {error}
            </p>
          )}
        </Dialog>
      )}
    </DetailSurface>
  );
}

export default PostDetail;
