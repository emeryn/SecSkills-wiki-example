import { CircleAlert, RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../lib/api-client";
import { Button } from "./Button";

interface ErrorStateProps {
  error: unknown;
  title?: string;
  onRetry?: () => void;
}

/** Persistent error banner: human-readable message, request id for support, optional retry. */
export function ErrorState({ error, title, onRetry }: ErrorStateProps) {
  const { t } = useTranslation();
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.code === "NETWORK_ERROR" ? t("errors.networkMessage") : t("errors.unexpectedMessage");

  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-danger/40 bg-danger/5 p-4"
    >
      <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-danger" />
      <div className="flex-1 space-y-1">
        <p className="font-medium">{title ?? t("errors.unexpectedTitle")}</p>
        <p className="text-text-muted">{message}</p>
        {apiError?.requestId != null && (
          <p className="font-mono text-xs text-text-muted">
            {t("errors.requestId", { requestId: apiError.requestId })}
          </p>
        )}
      </div>
      {onRetry !== undefined && (
        <Button onClick={onRetry} icon={<RotateCw aria-hidden className="size-4" />}>
          {t("errors.retry")}
        </Button>
      )}
    </div>
  );
}
