import { useTranslation } from "react-i18next";
import { ApiError } from "../../lib/api-client";

// The API words these itself, naming the rejected value's problem (never echoing input).
const SERVER_WORDED = new Set(["SETTING_REJECTED", "EXPORT_TOO_LARGE"]);

/** Message for a failed form submission; known API codes get a specific, safe wording. */
export function FormError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error === null || error === undefined) return null;
  const apiError = error instanceof ApiError ? error : null;
  const key = apiError !== null ? `apiErrors.${apiError.code}` : "";
  const message =
    apiError !== null && SERVER_WORDED.has(apiError.code)
      ? apiError.message
      : apiError !== null && t(key) !== key
        ? t(key)
        : apiError?.status === 429
          ? // The API says how long to wait; the proxy's own 429 has no JSON message.
            apiError.code === "RATE_LIMITED" && apiError.message !== ""
            ? apiError.message
            : t("errors.rateLimited")
          : t("errors.unexpectedMessage");
  return (
    <div
      role="alert"
      className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-danger"
    >
      <p>{message}</p>
      {apiError?.requestId != null && apiError.status >= 500 && (
        <p className="mt-1 font-mono text-xs">
          {t("errors.requestId", { requestId: apiError.requestId })}
        </p>
      )}
    </div>
  );
}
