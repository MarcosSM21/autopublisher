import Button from "./Button.tsx";
import Icon from "./Icon.tsx";

interface ErrorStateProps {
  /** Safe, user-facing message (already sanitised by the API). */
  message: string;
  title?: string;
  onRetry?: () => void;
}

/** A failure with a way forward: never an error without a next step. */
function ErrorState({
  message,
  title = "Something went wrong",
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="ap-error" role="alert">
      <Icon name="alert" className="ap-error__icon" />
      <div>
        <p className="ap-error__title">{title}</p>
        <p className="ap-error__text">{message}</p>
        {onRetry && (
          <Button variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}

export default ErrorState;
