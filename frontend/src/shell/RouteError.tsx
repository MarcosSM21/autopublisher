import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import Icon from "../ui/Icon.tsx";
import NotFound from "./NotFound.tsx";

/** errorElement of the root route: an unexpected error never leaves a blank page. */
function RouteError() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <main className="ap-route-error">
        <NotFound />
      </main>
    );
  }
  return (
    <main className="ap-route-error">
      <section className="ap-empty" aria-labelledby="route-error-heading">
        <span className="ap-empty__icon" aria-hidden="true">
          <Icon name="alert" />
        </span>
        <h1 id="route-error-heading" className="ap-empty__title">
          Something went wrong
        </h1>
        <p className="ap-empty__text">
          This page could not be shown. Try again from Home.
        </p>
        <p className="ap-empty__actions">
          <Link className="ap-button ap-button--primary" to="/">
            Go to Home
          </Link>
        </p>
      </section>
    </main>
  );
}

export default RouteError;
