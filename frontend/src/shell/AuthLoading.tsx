/**
 * While the session is unknown (AuthGate and /login): the monogram, which is
 * decorative, above the only announced text. No minimum duration, no delay.
 */
function AuthLoading() {
  return (
    <p className="ap-auth-loading" role="status">
      <span className="ap-mark ap-auth-loading__mark" aria-hidden="true" />
      <span>Loading AutoPublisher…</span>
    </p>
  );
}

export default AuthLoading;
