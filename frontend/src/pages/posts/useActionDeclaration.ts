import { useEffect, useState } from "react";
import { confirmTikTokConsent, getTikTokOptions } from "../../api.ts";
import {
  isDeclarationAccepted,
  useTikTokDeclaration,
} from "../../components/platform/tiktok-declaration.ts";
import type { Publication, TikTokPublicationOptions } from "../../types.ts";
import { toApiError } from "../../utils.ts";

/**
 * The single TikTok declaration of one Post detail action that publishes or
 * arms a Direct Post (research R-05): unchecked when the dialog opens,
 * recorded right before the action runs. Other platforms and Upload to Inbox
 * need none.
 */
export function useActionDeclaration(post: Publication, needed: boolean) {
  const control = useTikTokDeclaration();
  const tiktok = needed && post.account.platform === "tiktok";
  const [options, setOptions] = useState<TikTokPublicationOptions | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tiktok) {
      return;
    }
    let active = true;
    getTikTokOptions(post.id)
      .then((loaded) => active && setOptions(loaded))
      .catch(
        (caught: unknown) => active && setError(toApiError(caught).message),
      );
    return () => {
      active = false;
    };
  }, [tiktok, post.id]);

  const required = tiktok && options?.mode === "DIRECT_POST";
  const accepted = isDeclarationAccepted(control.accepted, options);
  return {
    control,
    options,
    error,
    /** The options are still loading (TikTok only). */
    loading: tiktok && options === null && error === null,
    required,
    /** True when nothing is needed, or the box matches the options. */
    ready: !required || accepted,
    inbox: tiktok && options?.mode === "INBOX_UPLOAD",
    /** Records the consent of exactly what was shown (TikTok Direct Post). */
    async record() {
      if (required && control.accepted) {
        await confirmTikTokConsent(
          post.id,
          control.accepted.fingerprint,
          control.accepted.version,
        );
      }
    },
  };
}
