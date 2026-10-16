import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { safeNextPath, STEP_ROUTES, useApplyStep, useSession } from "../../../lib/auth";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import type { EnrollmentResponse } from "../api";
import { RecoveryCodes } from "../components/RecoveryCodes";
import { SecurityKeyEnrollment } from "../components/SecurityKeyEnrollment";
import { TotpEnrollment } from "../components/TotpEnrollment";

/** Mandatory second-factor enrollment (administrators). */
export function SetupSecurityPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const session = useSession();
  const applyStep = useApplyStep();
  const [codes, setCodes] = useState<string[] | null>(null);

  if (codes !== null) {
    return (
      <AuthLayout title={t("setup.securityDoneTitle")}>
        <RecoveryCodes codes={codes} />
        <Button
          variant="primary"
          className="w-full"
          onClick={() => {
            void navigate(next);
          }}
        >
          {t("setup.continue")}
        </Button>
      </AuthLayout>
    );
  }
  if (session.isPending) return null;
  if (session.data === null) return <Navigate to="/login" replace />;
  if (session.data !== undefined && session.data.state !== "mfa_enrollment_required") {
    const state = session.data.state;
    return (
      <Navigate
        to={state === "active" ? next : `${STEP_ROUTES[state]}?next=${encodeURIComponent(next)}`}
        replace
      />
    );
  }

  const enrolled = async (result: EnrollmentResponse) => {
    // Codes first: refreshing the session makes it active, which would redirect away.
    if (result.recovery_codes.length > 0) setCodes(result.recovery_codes);
    await applyStep(result);
    if (result.recovery_codes.length === 0) await navigate(next);
  };
  return (
    <AuthLayout title={t("setup.securityTitle")}>
      <p className="text-text-muted">{t("setup.securityHelp")}</p>
      <section className="space-y-2">
        <h2 className="font-semibold">{t("account.authenticatorApp")}</h2>
        <TotpEnrollment onEnrolled={(result) => void enrolled(result)} />
      </section>
      <section className="space-y-2">
        <h2 className="font-semibold">{t("account.securityKeys")}</h2>
        <SecurityKeyEnrollment onEnrolled={(result) => void enrolled(result)} />
      </section>
    </AuthLayout>
  );
}
