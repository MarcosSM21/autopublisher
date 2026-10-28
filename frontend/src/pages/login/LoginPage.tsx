import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";
import { login } from "../../api.ts";
import AuthLoading from "../../shell/AuthLoading.tsx";
import {
  markSignedIn,
  requiresSignIn,
  safeNext,
  useAuthSession,
} from "../../shell/useAuthSession.ts";
import Button from "../../ui/Button.tsx";
import Field from "../../ui/Field.tsx";
import Icon from "../../ui/Icon.tsx";
import { toApiError } from "../../utils.ts";
import "./login.css";

const ERRORS: Record<string, string> = {
  invalid_credentials: "Incorrect password.",
  too_many_attempts: "Too many attempts. Try again in a few minutes.",
  network_error:
    "Could not reach AutoPublisher. Check that it is running and try again.",
};

/**
 * The installation password (contracts/ui.md §2), outside the app shell. Once
 * signed in, the browser returns to `next` (the original deep link); a signed-in
 * visitor (or development, which has no sign-in) never sees the form.
 */
function LoginPage() {
  const auth = useAuthSession();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  // Only the input holds the password: never stored, logged or put in a URL.
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (auth.status === "ready" && !requiresSignIn(auth.session)) {
    return <Navigate to={next} replace />;
  }
  if (auth.status === "loading") {
    return <AuthLoading />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) {
      return;
    }
    if (password === "") {
      setError("Enter the password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(password);
      setPassword("");
      // `auth_not_enabled` (development) also lands here through the reload.
      await markSignedIn();
    } catch (caught) {
      const apiError = toApiError(caught);
      setPassword("");
      if (apiError.code === "auth_not_enabled") {
        await markSignedIn();
        return;
      }
      setError(ERRORS[apiError.code] ?? "Could not sign in. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="ap-login">
      <form
        className="ap-login__card"
        aria-labelledby="login-title"
        onSubmit={(event) => void handleSubmit(event)}
        noValidate
      >
        <h1 id="login-title" className="ap-login__title">
          <span className="ap-mark" aria-hidden="true" />
          AutoPublisher
        </h1>
        <Field label="Password">
          {(control) => (
            <input
              {...control}
              type="password"
              name="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        {error && (
          <p className="error ap-login__error" role="alert">
            <Icon name="alert" className="ap-login__error-icon" />
            {error}
          </p>
        )}
        <Button variant="primary" type="submit" loading={busy}>
          Sign in
        </Button>
        <p className="ap-meta ap-login__hint">
          Forgot the password? Reset it on the computer that runs AutoPublisher
          (see the deployment guide, “Reset the password”).
        </p>
      </form>
    </main>
  );
}

export default LoginPage;
