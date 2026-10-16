import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { hasPermission, STEP_ROUTES, useSession } from "../lib/auth";
import { NotFoundPage } from "./NotFoundPage";

/** Signed-in, fully authenticated users only; others go to the sign-in step they are at. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.isPending) {
    return (
      <div className="p-6">
        <Skeleton className="h-8 w-64" />
      </div>
    );
  }
  if (session.isError) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState error={session.error} onRetry={() => void session.refetch()} />
      </div>
    );
  }
  const next = encodeURIComponent(location.pathname + location.search);
  if (session.data === null) return <Navigate to={`/login?next=${next}`} replace />;
  if (session.data.state !== "active") {
    return <Navigate to={`${STEP_ROUTES[session.data.state]}?next=${next}`} replace />;
  }
  return <>{children}</>;
}

/** UI convenience only: the API enforces every permission. Unknown to the user = not found. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const session = useSession();
  return hasPermission(session.data, permission) ? <>{children}</> : <NotFoundPage />;
}
