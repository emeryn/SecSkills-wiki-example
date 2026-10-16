import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ToastProvider } from "../components/ui/Toast";
import { ReauthProvider } from "../features/auth/components/ReauthProvider";
import { ApiError, setCsrfToken, setUnauthenticatedHandler } from "../lib/api-client";
import { SESSION_KEY } from "../lib/auth";

const MAX_RETRIES = 2;

/** Client errors (4xx) are final; network and server errors are retried twice. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  useEffect(() => {
    // Session expired or revoked: forget it; the route guard sends the user to sign-in.
    setUnauthenticatedHandler(() => {
      setCsrfToken(null);
      queryClient.setQueryData(SESSION_KEY, null);
    });
    return () => {
      setUnauthenticatedHandler(null);
    };
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ReauthProvider>{children}</ReauthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
