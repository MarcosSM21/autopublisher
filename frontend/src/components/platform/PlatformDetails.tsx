import { useCallback, useEffect, useId, useState } from "react";
import { getPublishCheck } from "../../api.ts";
import {
  platformLabel,
  type Publication,
  type PublishCheck,
  type TikTokPublicationOptions,
} from "../../types.ts";
import Badge, { type Tone } from "../../ui/Badge.tsx";
import Button from "../../ui/Button.tsx";
import Disclosure from "../../ui/Disclosure.tsx";
import type { IconName } from "../../ui/Icon.tsx";
import Skeleton from "../../ui/Skeleton.tsx";
import { accountReference, toApiError } from "../../utils.ts";
import InstagramDetails from "./InstagramDetails.tsx";
import {
  platformState,
  READINESS_LABELS,
  telegramChannel,
  type PlatformReadiness,
} from "./platform-state.ts";
import TelegramDetails from "./TelegramDetails.tsx";
import ThreadsDetails from "./ThreadsDetails.tsx";
import {
  isDeclarationAccepted,
  useTikTokDeclaration,
  type DeclarationControl,
} from "./tiktok-declaration.ts";
import TikTokDetails from "./TikTokDetails.tsx";
import type { AutosaveView } from "./types.ts";
import YouTubeDetails from "./YouTubeDetails.tsx";
import "./platform.css";

const READINESS_LOOK: Record<
  PlatformReadiness,
  { tone: Tone; icon: IconName }
> = {
  ready: { tone: "success", icon: "check" },
  details_needed: { tone: "warning", icon: "alert" },
  blocked: { tone: "danger", icon: "alert" },
  checking: { tone: "neutral", icon: "clock" },
};

const AUTOSAVE_TEXT: Record<AutosaveView["status"], string> = {
  idle: "",
  saving: "Saving…",
  saved: "Saved",
  error: "Couldn't save",
};

interface PlatformDetailsProps {
  publication: Publication;
  /**
   * The TikTok declaration of the action, owned by whoever runs it (Publish,
   * the action dialog). Without it the card keeps its own, unchecked on mount.
   */
  tiktokDeclaration?: DeclarationControl;
  /**
   * Id of the card, so an error summary or "Complete details" can reach it;
   * the TikTok declaration checkbox is `<id>-declaration`.
   */
  id?: string;
  /** Level of the card's heading in its page (default 3). */
  headingLevel?: 3 | 4;
  /**
   * The TikTok declaration is shown here (Publish). In Post detail it lives in
   * the dialog of the action that needs it, so the card never shows a second.
   */
  showDeclaration?: boolean;
  /**
   * A Post that can't be published any more (Published, Publishing…): no
   * readiness state, folded, options read-only as the backend says.
   */
  history?: boolean;
  /** Changing it opens the card (e.g. "Complete details"). */
  openRequest?: number;
}

/**
 * The platform details of one Post: a card with the platform, the account, the
 * human state (Ready / Details needed / Blocked / Checking) and the autosave
 * status. Ready starts collapsed and anything missing starts open. Every
 * change is saved on its own; after each save the publish check is read again.
 */
function PlatformDetails({
  publication,
  tiktokDeclaration,
  id,
  headingLevel = 3,
  showDeclaration = true,
  history = false,
  openRequest = 0,
}: PlatformDetailsProps) {
  const headingId = useId();
  const Heading = headingLevel === 4 ? "h4" : "h3";
  const platform = publication.account.platform;
  const [check, setCheck] = useState<PublishCheck | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [autosave, setAutosave] = useState<AutosaveView>({
    status: "idle",
    error: null,
    retry: () => {},
  });
  const [tiktokOptions, setTikTokOptions] =
    useState<TikTokPublicationOptions | null>(null);
  const ownDeclaration = useTikTokDeclaration();
  const declaration = tiktokDeclaration ?? ownDeclaration;
  // null until the user toggles it, or until the first state is known.
  const [open, setOpen] = useState<boolean | null>(history ? false : null);
  const [seenRequest, setSeenRequest] = useState(openRequest);
  if (openRequest !== seenRequest) {
    setSeenRequest(openRequest);
    setOpen(true);
  }

  const loadCheck = useCallback(
    () =>
      getPublishCheck(publication.id)
        .then((loaded) => {
          setCheck(loaded);
          setCheckError(null);
        })
        .catch((caught: unknown) => setCheckError(toApiError(caught).message)),
    [publication.id],
  );

  // Read again when the state or the caption changes (e.g. an override saved).
  const captionKey = `${publication.description ?? ""}\n${publication.hashtags.join(" ")}`;
  useEffect(() => {
    if (!history) {
      void loadCheck();
    }
  }, [loadCheck, publication.status, captionKey, history]);

  const accountPath = `/p/${publication.project_id}/accounts/${publication.account_id}`;
  const readiness = platformState({
    platform,
    check,
    // Without the declaration here, the action's dialog asks for it.
    declarationAccepted:
      !showDeclaration ||
      isDeclarationAccepted(declaration.accepted, tiktokOptions),
    accountPath,
  });
  // The first known state decides; later saves never fold the card away.
  if (open === null && readiness.state !== "checking") {
    setOpen(readiness.state !== "ready");
  }

  const formProps = {
    publication,
    captionKey,
    registryKey: `post-${publication.id}`,
    onSaved: () => {
      if (!history) {
        void loadCheck();
      }
    },
    onAutosaveChange: setAutosave,
  };
  const look = READINESS_LOOK[readiness.state];

  return (
    <section
      id={id}
      tabIndex={-1}
      className="ap-platform-card"
      aria-labelledby={headingId}
      aria-busy={(!history && readiness.state === "checking") || undefined}
    >
      <div className="ap-platform-card__header">
        <Heading id={headingId} className="ap-platform-card__title">
          {platformLabel(platform)}{" "}
          <span className="ap-meta">
            {accountReference(publication.account)}
          </span>
        </Heading>
        {!history && (
          <Badge tone={look.tone} icon={look.icon}>
            {READINESS_LABELS[readiness.state]}
          </Badge>
        )}
      </div>
      {!history &&
        readiness.state !== "ready" &&
        readiness.state !== "checking" && (
          <p className="ap-platform-card__summary">{readiness.summary}</p>
        )}
      {readiness.state === "ready" && platform === "telegram" && (
        <p className="ap-platform-card__summary">
          Posts to {telegramChannel(check)}
        </p>
      )}
      {readiness.blockers.some((blocker) => blocker.action) && (
        <ul className="ap-platform-card__actions">
          {readiness.blockers
            .filter((blocker) => blocker.action)
            .map((blocker) => (
              <li key={blocker.message}>
                <Button as="link" to={blocker.action!.to} variant="secondary">
                  {blocker.action!.label}
                </Button>
              </li>
            ))}
        </ul>
      )}
      <div className="ap-platform-card__autosave">
        <p className="ap-meta" aria-live="polite">
          {AUTOSAVE_TEXT[autosave.status]}
          {autosave.status === "error" && autosave.error
            ? `: ${autosave.error}`
            : ""}
        </p>
        {autosave.status === "error" && (
          <Button variant="ghost" onClick={autosave.retry}>
            Retry
          </Button>
        )}
      </div>
      {checkError && (
        <div className="ap-platform-card__check-error" role="alert">
          <p>Couldn't check this destination: {checkError}</p>
          <Button onClick={() => void loadCheck()}>Retry</Button>
        </div>
      )}
      <Disclosure
        label="Details"
        open={open ?? false}
        onOpenChange={setOpen}
        className="ap-platform-card__details"
      >
        {!history && readiness.state === "checking" && !checkError && (
          <Skeleton lines={2} label="Checking the details…" />
        )}
        {platform === "youtube" && <YouTubeDetails {...formProps} />}
        {platform === "instagram" && <InstagramDetails {...formProps} />}
        {platform === "threads" && <ThreadsDetails {...formProps} />}
        {platform === "tiktok" && (
          <TikTokDetails
            {...formProps}
            declaration={declaration}
            showDeclaration={showDeclaration}
            declarationId={id ? `${id}-declaration` : undefined}
            onOptionsChange={setTikTokOptions}
          />
        )}
        {platform === "telegram" && <TelegramDetails check={check} />}
      </Disclosure>
    </section>
  );
}

export default PlatformDetails;
