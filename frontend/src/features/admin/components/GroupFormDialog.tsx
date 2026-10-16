import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { newIdempotencyKey } from "../../../lib/api-client";
import { adminApi } from "../api";
import { groupFormSchema, type GroupForm } from "../schemas";

export function CreateGroupDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const key = useRef(newIdempotencyKey());
  const form = useForm<GroupForm>({
    resolver: zodResolver(groupFormSchema),
    mode: "onBlur",
    defaultValues: { name: "", description: "" },
  });
  const create = useMutation({
    mutationFn: (values: GroupForm) => adminApi.createGroup(values, key.current),
    onSuccess: async (group) => {
      key.current = newIdempotencyKey();
      form.reset();
      onOpenChange(false);
      await queryClient.invalidateQueries({ queryKey: ["admin", "groups"] });
      await navigate(`/admin/groups/${group.id}`);
    },
  });
  const message = (value: string | undefined) => (value !== undefined ? t(value) : undefined);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t("admin.createGroup")}>
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
          label={t("admin.groupName")}
          required
          autoFocus
          error={message(form.formState.errors.name?.message)}
          {...form.register("name")}
        />
        <TextField
          label={t("admin.description")}
          error={message(form.formState.errors.description?.message)}
          {...form.register("description")}
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
