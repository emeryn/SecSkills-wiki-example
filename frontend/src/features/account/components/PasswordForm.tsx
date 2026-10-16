import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { useApplyStep, type SessionState } from "../../../lib/auth";
import { newPasswordSchema } from "../../../lib/password-schema";
import { accountApi } from "../api";

const schema = newPasswordSchema.and(
  z.object({ currentPassword: z.string().min(1, "validation.required") }),
);
type PasswordValues = z.infer<typeof schema>;

/** Change password; every other session is signed out by the server. */
export function PasswordForm({ onDone }: { onDone: (state: SessionState) => void }) {
  const { t } = useTranslation();
  const applyStep = useApplyStep();
  const form = useForm<PasswordValues>({ resolver: zodResolver(schema), mode: "onBlur" });
  const change = useMutation({
    mutationFn: (values: PasswordValues) =>
      accountApi.changePassword(values.currentPassword, values.newPassword),
    onSuccess: async (step) => {
      form.reset();
      onDone(await applyStep(step));
    },
  });
  const message = (key: string | undefined) => (key !== undefined ? t(key) : undefined);

  return (
    <form
      noValidate
      className="max-w-md space-y-4"
      onSubmit={(event) =>
        void form.handleSubmit((values) => {
          change.mutate(values);
        })(event)
      }
    >
      <TextField
        label={t("account.currentPassword")}
        type="password"
        autoComplete="current-password"
        required
        error={message(form.formState.errors.currentPassword?.message)}
        {...form.register("currentPassword")}
      />
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
      <FormError error={change.error} />
      <Button type="submit" variant="primary" loading={change.isPending}>
        {t("account.changePassword")}
      </Button>
    </form>
  );
}
