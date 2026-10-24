import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import ErrorState from "../ui/ErrorState.tsx";
import {
  loginPath,
  requiresSignIn,
  retryAuthSession,
  useAuthSession,
} from "./useAuthSession.ts";

/**
 * Renders the app only once the session is known (contracts/ui.md §1): until
 * then nothing that requests private data is mounted. An installation without a
 * session goes to /login with the current path and query as `next`;
 * development has no sign-in and renders the app directly.
 */
function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuthSession();
  const location = useLocation();

  if (auth.status === "loading") {
    return (
      <p className="ap-auth-loading" role="status">
        Loading AutoPublisher…
      </p>
    );
  }
  if (auth.status === "error") {
    return (
      <main className="ap-auth-loading">
        <ErrorState
          title="Couldn't reach AutoPublisher"
          message={auth.error.message}
          onRetry={() => void retryAuthSession()}
        />
      </main>
    );
  }
  if (requiresSignIn(auth.session)) {
    return <Navigate to={loginPath(location)} replace />;
  }
  return children;
}

export default AuthGate;
