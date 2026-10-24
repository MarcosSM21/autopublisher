import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";

export const FLASH_DURATION_MS = 4000;

/** Router state that carries a one-time message to the next page. */
export interface FlashState {
  flash?: string;
}

/**
 * Shows the `flash` of the navigation that just happened ("Post deleted.") in a
 * live region, hides it after a few seconds and removes it from the history
 * entry, so Back or a reload never shows it again (contracts/ui.md §1).
 */
function Flash() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as FlashState | null;
  const incoming = typeof state?.flash === "string" ? state.flash : null;
  const [shown, setShown] = useState<{ key: string; text: string } | null>(
    null,
  );
  // Adopted during render, keyed by the history entry that brought it.
  if (incoming !== null && shown?.key !== location.key) {
    setShown({ key: location.key, text: incoming });
  }

  useEffect(() => {
    if (incoming === null) {
      return;
    }
    const { flash: _flash, ...rest } = state ?? {};
    void navigate(
      { pathname: location.pathname, search: location.search },
      { replace: true, state: Object.keys(rest).length > 0 ? rest : null },
    );
  }, [incoming, state, navigate, location.pathname, location.search]);

  useEffect(() => {
    if (shown === null) {
      return;
    }
    const timer = window.setTimeout(() => setShown(null), FLASH_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [shown]);

  return (
    <div className="ap-flash" role="status">
      {shown && <p className="ap-flash__message">{shown.text}</p>}
    </div>
  );
}

export default Flash;
