import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { safeNextPath, STEP_ROUTES, useApplyStep, useSession } from "../../../lib/auth";
import { authApi } from "../api";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import { FormError } from "../../../components/ui/FormError";
import { loginSchema, type LoginForm } from "../schemas";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get("next"));
  const session = useSession();
  const applyStep = useApplyStep();
  const form = useForm<LoginForm>({ resolver: zodResolver(loginSchema), mode: "onBlur" });
  const methods = useQuery({ queryKey: ["auth", "methods"], queryFn: authApi.methods });
  const ssoError = params.get("error");

  const login = useMutation({
    mutationFn: (values: LoginForm) => authApi.login(values.username, values.password),
    onSuccess: async (step) => {
      const state = await applyStep(step);
      const target = state === "active" ? next : STEP_ROUTES[state];
      await navigate(state === "active" ? target : `${target}?next=${encodeURIComponent(next)}`);
    },
  });

  if (session.data?.state === "active") return <Navigate to={next} replace />;

  const errorText = (key: string | undefined) => (key !== undefined ? t(key) : undefined);
  return (
    <AuthLayout title={t("auth.signInTitle")}>
      {ssoError !== null && (
        <div
          role="alert"
          className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-danger"
        >
          {ssoError === "sso_unavailable" ? t("auth.ssoUnavailable") : t("auth.ssoFailed")}
        </div>
      )}
      {methods.data?.oidc === true && (
        <>
          {/* A navigation, not an API call: the server redirects to the identity provider. */}
          <a
            href={`/api/v1/auth/oidc/start?next=${encodeURIComponent(next)}`}
            className="flex h-9 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover"
          >
            {t("auth.signInWith", { name: methods.data.oidc_label })}
          </a>
          <p className="text-center text-xs text-text-muted">{t("auth.orLocal")}</p>
        </>
      )}
      <form
        noValidate
        className="space-y-4"
        onSubmit={(event) =>
          void form.handleSubmit((values) => {
            login.mutate(values);
          })(event)
        }
      >
        <TextField
          label={t("auth.username")}
          autoComplete="username"
          autoFocus
          required
          error={errorText(form.formState.errors.username?.message)}
          {...form.register("username")}
        />
        <TextField
          label={t("auth.password")}
          type="password"
          autoComplete="current-password"
          required
          error={errorText(form.formState.errors.password?.message)}
          {...form.register("password")}
        />
        <FormError error={login.error} />
        <Button
          type="submit"
          variant={methods.data?.oidc === true ? "secondary" : "primary"}
          loading={login.isPending}
          className="w-full"
        >
          {t("auth.signIn")}
        </Button>
      </form>
      <Link to="/forgot-password" className="block text-center text-primary hover:underline">
        {t("auth.forgotPassword")}
      </Link>
    </AuthLayout>
  );
}
