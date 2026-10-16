import { isRouteErrorResponse, useRouteError } from "react-router";
import { ErrorState } from "../components/ui/ErrorState";
import { NotFoundPage } from "./NotFoundPage";

/** Router error boundary: never shows stack traces, only a message and the request id. */
export function RouteError() {
  const error = useRouteError();
  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundPage />;
  }
  return (
    <div className="mx-auto max-w-xl p-6">
      <ErrorState
        error={error}
        onRetry={() => {
          window.location.reload();
        }}
      />
    </div>
  );
}
