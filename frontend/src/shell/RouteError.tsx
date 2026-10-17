import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import NotFound from "./NotFound.tsx";

/** errorElement of the root route: an unexpected error never leaves a blank page. */
function RouteError() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <main>
        <NotFound />
      </main>
    );
  }
  return (
    <main>
      <section aria-labelledby="route-error-heading">
        <h1 id="route-error-heading">Something went wrong</h1>
        <p>This page could not be shown. Try again from Home.</p>
        <p>
          <Link to="/">Go to Home</Link>
        </p>
      </section>
    </main>
  );
}

export default RouteError;
