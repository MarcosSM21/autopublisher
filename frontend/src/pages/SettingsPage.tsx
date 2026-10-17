import AutomationStatus from "../components/AutomationStatus.tsx";
import PlatformConfigurationList from "./settings/PlatformConfigurationList.tsx";
import "./settings/settings.css";

/**
 * Two questions only: is automatic publishing running, and are the platform
 * integrations configured? The global Pause/Resume lives here and nowhere else.
 */
function SettingsPage() {
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
      <section
        className="ap-settings__section"
        aria-labelledby="settings-platforms"
      >
        <h2 id="settings-platforms" className="ap-section-title">
          Platform integrations
        </h2>
        <PlatformConfigurationList />
      </section>
    </div>
  );
}

export default SettingsPage;
