import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { newIdempotencyKey } from "../../../lib/api-client";
import { adminApi, type Link } from "../api";
import { userFormSchema, type UserForm } from "../schemas";

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (invitation: Link) => void;
}

export function CreateUserDialog({ open, onOpenChange, onCreated }: CreateUserDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // One key per user action, reused if the same submission is retried.
  const key = useRef(newIdempotencyKey());
  const form = useForm<UserForm>({
    resolver: zodResolver(userFormSchema),
    mode: "onBlur",
    defaultValues: { username: "", email: "", display_name: "", role: "user" },
  });
  const create = useMutation({
    mutationFn: (values: UserForm) =>
      adminApi.createUser(
        {
          username: values.username,
          email: values.email || undefined,
          display_name: values.display_name || undefined,
          role: values.role,
        },
        key.current,
      ),
    onSuccess: async (result) => {
      key.current = newIdempotencyKey();
      form.reset();
      onOpenChange(false);
      onCreated(result.invitation);
      await queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
  });
  const message = (value: string | undefined) => (value !== undefined ? t(value) : undefined);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("admin.createUser")}
      description={t("admin.createUserHelp")}
    >
      <form
        noValidate
        className="space-y-4"
        onSubmit={(event) =>
          void form.handleSubmit((values) => {
            create.mutate(values);
          })(event)
        }
      >
        <TextField
          label={t("auth.username")}
          required
          autoFocus
          error={message(form.formState.errors.username?.message)}
          {...form.register("username")}
        />
        <TextField
          label={t("auth.email")}
          type="email"
          error={message(form.formState.errors.email?.message)}
          {...form.register("email")}
        />
        <TextField
          label={t("account.displayName")}
          error={message(form.formState.errors.display_name?.message)}
          {...form.register("display_name")}
        />
        <SelectField
          label={t("account.role")}
          options={[
            { value: "user", label: t("roles.user") },
            { value: "admin", label: t("roles.admin") },
          ]}
          {...form.register("role")}
        />
        <FormError error={create.error} />
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
