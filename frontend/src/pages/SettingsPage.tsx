import { useState } from "react";
import { useNavigate } from "react-router";
import { logout } from "../api.ts";
import AutomationStatus from "../components/AutomationStatus.tsx";
import { markSignedOut, useAuthSession } from "../shell/useAuthSession.ts";
import Button from "../ui/Button.tsx";
import { toApiError } from "../utils.ts";
import ChangePasswordDialog from "./settings/ChangePasswordDialog.tsx";
import InstallationStatus from "./settings/InstallationStatus.tsx";
import PlatformConfigurationList from "./settings/PlatformConfigurationList.tsx";
import "./settings/settings.css";

/**
 * Is automatic publishing running, and are the platform integrations
 * configured? The installed app adds its own status and the sign-in actions
 * (Feature 020); development, which has no sign-in, shows neither. The global
 * Pause/Resume lives here and nowhere else.
 */
function SettingsPage() {
  const auth = useAuthSession();
  const installation =
    auth.status === "ready" && auth.session.mode === "installation";
  return (
    <div className="ap-settings">
      <h1 className="ap-page-title">Settings</h1>
      <section
        className="ap-settings__section"
        aria-labelledby="settings-automation"
      >
        <h2 id="settings-automation" className="ap-section-title">
          Automatic publishing
        </h2>
        <AutomationStatus />
      </section>
      {installation && (
        <section
          className="ap-settings__section"
          aria-labelledby="settings-installation"
        >
          <h2 id="settings-installation" className="ap-section-title">
            This installation
          </h2>
          <InstallationStatus />
        </section>
      )}
      <section
        className="ap-settings__section"
        aria-labelledby="settings-platforms"
      >
        <h2 id="settings-platforms" className="ap-section-title">
          Platform integrations
        </h2>
        <PlatformConfigurationList />
      </section>
      {installation && <SignInSection />}
    </div>
  );
}

function SignInSection() {
  const navigate = useNavigate();
  const [changing, setChanging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    setError(null);
    try {
      await logout();
    } catch (caught) {
      // Idempotent on the server: only an unreachable server is a real failure.
      if (toApiError(caught).code === "network_error") {
        setError("Could not reach AutoPublisher. Try again in a moment.");
        setSigningOut(false);
        return;
      }
    }
    markSignedOut();
    void navigate("/login", { replace: true });
  }

  return (
    <section className="ap-settings__section" aria-labelledby="settings-signin">
      <h2 id="settings-signin" className="ap-section-title">
        Sign-in
      </h2>
      <div className="ap-signin">
        {notice && (
          <p className="ap-signin__notice" role="status">
            {notice}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="ap-signin__actions">
          <Button
            onClick={() => {
              setNotice(null);
              setChanging(true);
            }}
          >
            Change password
          </Button>
          <Button loading={signingOut} onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
      </div>
      <ChangePasswordDialog
        open={changing}
        onOpenChange={setChanging}
        onChanged={() => {
          setChanging(false);
          setNotice("Password changed. Other devices have been signed out.");
        }}
      />
    </section>
  );
}

export default SettingsPage;
