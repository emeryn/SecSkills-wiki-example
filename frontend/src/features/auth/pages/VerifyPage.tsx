import { zodResolver } from "@hookform/resolvers/zod";
import { startAuthentication } from "@simplewebauthn/browser";
import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import {
  safeNextPath,
  STEP_ROUTES,
  useApplyStep,
  useSession,
  type StepResponse,
} from "../../../lib/auth";
import { authApi, type WebAuthnJson } from "../api";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import { FormError } from "../../../components/ui/FormError";
import { codeSchema, type CodeForm } from "../schemas";

type Method = "totp" | "recovery";

/** Second factor of sign-in: authenticator code, security key or recovery code. */
export function VerifyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const session = useSession();
  const applyStep = useApplyStep();
  const [method, setMethod] = useState<Method>("totp");
  const form = useForm<CodeForm>({ resolver: zodResolver(codeSchema) });

  const done = async (step: StepResponse) => {
    const state = await applyStep(step);
    await navigate(
      state === "active" ? next : `${STEP_ROUTES[state]}?next=${encodeURIComponent(next)}`,
    );
  };
  const verifyCode = useMutation({
    mutationFn: (values: CodeForm) =>
      method === "totp" ? authApi.verifyTotp(values.code) : authApi.verifyRecoveryCode(values.code),
    onSuccess: done,
  });
  const verifyKey = useMutation({
    mutationFn: async () => {
      const options = await authApi.webauthnOptions();
      const credential = await startAuthentication({ optionsJSON: options as never });
      return authApi.verifyWebauthn(credential as unknown as WebAuthnJson);
    },
    onSuccess: done,
  });

  if (session.isPending) return null;
  if (session.data === null) return <Navigate to="/login" replace />;
  if (session.data !== undefined && session.data.state !== "mfa_required") {
    return (
      <Navigate
        to={session.data.state === "active" ? next : STEP_ROUTES[session.data.state]}
        replace
      />
    );
  }
  const methods = session.data?.mfa_methods ?? [];

  return (
    <AuthLayout title={t("auth.verifyTitle")}>
      {methods.includes("webauthn") && (
        <Button
          className="w-full"
          variant="primary"
          loading={verifyKey.isPending}
          icon={<KeyRound aria-hidden className="size-4" />}
          onClick={() => {
            verifyKey.mutate();
          }}
        >
          {t("auth.useSecurityKey")}
        </Button>
      )}
      <FormError error={verifyKey.error} />
      <form
        noValidate
        className="space-y-4"
        onSubmit={(event) =>
          void form.handleSubmit((values) => {
            verifyCode.mutate(values);
          })(event)
        }
      >
        <TextField
          label={method === "totp" ? t("auth.authenticatorCode") : t("auth.recoveryCode")}
          inputMode={method === "totp" ? "numeric" : "text"}
          autoComplete="one-time-code"
          autoFocus={!methods.includes("webauthn")}
          required
          error={
            form.formState.errors.code?.message !== undefined
              ? t(form.formState.errors.code.message)
              : undefined
          }
          {...form.register("code")}
        />
        <FormError error={verifyCode.error} />
        <Button type="submit" loading={verifyCode.isPending} className="w-full">
          {t("auth.verify")}
        </Button>
      </form>
      <button
        type="button"
        className="block w-full text-center text-primary hover:underline"
        onClick={() => {
          setMethod(method === "totp" ? "recovery" : "totp");
          form.reset();
        }}
      >
        {method === "totp" ? t("auth.useRecoveryCode") : t("auth.useAuthenticator")}
      </button>
    </AuthLayout>
  );
}
