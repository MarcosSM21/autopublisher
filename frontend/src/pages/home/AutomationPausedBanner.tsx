import Button from "../../ui/Button.tsx";
import Icon from "../../ui/Icon.tsx";

/** Global pause: explains the effect and points to Settings (no toggle here). */
function AutomationPausedBanner({ affected }: { affected: number }) {
  return (
    <section className="ap-home-banner" aria-labelledby="home-paused-title">
      <Icon name="pause" className="ap-home-banner__icon" />
      <div className="ap-home-banner__body">
        <h2 id="home-paused-title" className="ap-home-banner__title">
          Automatic publishing is paused
        </h2>
        <p className="ap-home-banner__text">
          {affected > 0
            ? `${affected} scheduled ${affected === 1 ? "post won't" : "posts won't"} publish until you resume it.`
            : "Scheduled posts won't publish until you resume it."}
        </p>
      </div>
      <Button as="link" to="/settings" variant="secondary">
        Go to Settings
      </Button>
    </section>
  );
}

export default AutomationPausedBanner;
