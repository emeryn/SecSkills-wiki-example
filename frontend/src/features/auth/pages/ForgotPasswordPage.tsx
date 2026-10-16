import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { authApi } from "../api";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import { FormError } from "../../../components/ui/FormError";
import { resetRequestSchema, type ResetRequestForm } from "../schemas";

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const form = useForm<ResetRequestForm>({
    resolver: zodResolver(resetRequestSchema),
    mode: "onBlur",
  });
  const request = useMutation({
    mutationFn: (values: ResetRequestForm) => authApi.requestReset(values.email),
  });

  return (
    <AuthLayout title={t("auth.forgotTitle")}>
      {request.isSuccess ? (
        <p role="status">{t("auth.resetRequested")}</p>
      ) : (
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) =>
            void form.handleSubmit((values) => {
              request.mutate(values);
            })(event)
          }
        >
          <p className="text-text-muted">{t("auth.forgotHelp")}</p>
          <TextField
            label={t("auth.email")}
            type="email"
            autoComplete="email"
            required
            error={
              form.formState.errors.email?.message !== undefined
                ? t(form.formState.errors.email.message)
                : undefined
            }
            {...form.register("email")}
          />
          <FormError error={request.error} />
          <Button type="submit" variant="primary" loading={request.isPending} className="w-full">
            {t("auth.sendResetLink")}
          </Button>
        </form>
      )}
      <Link to="/login" className="block text-center text-primary hover:underline">
        {t("auth.backToSignIn")}
      </Link>
    </AuthLayout>
  );
}
