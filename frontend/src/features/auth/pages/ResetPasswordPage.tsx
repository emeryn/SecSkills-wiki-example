import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { authApi } from "../api";
import { AuthLayout } from "../../../components/ui/AuthLayout";
import { FormError } from "../../../components/ui/FormError";
import { newPasswordSchema, type NewPasswordForm } from "../schemas";

/** Target of reset and invitation links (`/reset-password?token=...`). */
export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const form = useForm<NewPasswordForm>({
    resolver: zodResolver(newPasswordSchema),
    mode: "onBlur",
  });
  const confirm = useMutation({
    mutationFn: (values: NewPasswordForm) => authApi.confirmReset(token, values.newPassword),
  });
  const message = (key: string | undefined) => (key !== undefined ? t(key) : undefined);

  return (
    <AuthLayout title={t("auth.resetTitle")}>
      {confirm.isSuccess ? (
        <div className="space-y-4">
          <p role="status">{t("auth.resetDone")}</p>
          <Link to="/login" className="block text-center text-primary hover:underline">
            {t("auth.signIn")}
          </Link>
        </div>
      ) : (
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) =>
            void form.handleSubmit((values) => {
              confirm.mutate(values);
            })(event)
          }
        >
          <TextField
            label={t("account.newPassword")}
            type="password"
            autoComplete="new-password"
            hint={t("account.passwordHint")}
            required
            error={message(form.formState.errors.newPassword?.message)}
            {...form.register("newPassword")}
          />
          <TextField
            label={t("account.confirmPassword")}
            type="password"
            autoComplete="new-password"
            required
            error={message(form.formState.errors.confirmation?.message)}
            {...form.register("confirmation")}
          />
          <FormError error={confirm.error} />
          <Button type="submit" variant="primary" loading={confirm.isPending} className="w-full">
            {t("auth.setPassword")}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
