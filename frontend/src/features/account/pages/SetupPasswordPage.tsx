import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { safeNextPath, STEP_ROUTES, useSession } from "../../../lib/auth";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import { PasswordForm } from "../components/PasswordForm";

/** Forced password change (bootstrap administrator, password set by an administrator). */
export function SetupPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const session = useSession();

  if (session.isPending) return null;
  if (session.data === null) return <Navigate to="/login" replace />;
  if (session.data !== undefined && session.data.state !== "password_change_required") {
    const state = session.data.state;
    return (
      <Navigate
        to={state === "active" ? next : `${STEP_ROUTES[state]}?next=${encodeURIComponent(next)}`}
        replace
      />
    );
  }
  return (
    <AuthLayout title={t("setup.passwordTitle")}>
      <p className="text-text-muted">{t("setup.passwordHelp")}</p>
      <PasswordForm
        onDone={(state) => {
          void navigate(
            state === "active" ? next : `${STEP_ROUTES[state]}?next=${encodeURIComponent(next)}`,
          );
        }}
      />
    </AuthLayout>
  );
}
