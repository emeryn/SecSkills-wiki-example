import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { ErrorState } from "../../../components/ui/ErrorState";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { formatDateTime } from "../../../lib/format";
import { useUnsavedChangesWarning } from "../../../lib/unsaved-changes";
import { adminApi, type Link } from "../api";
import { LinkDialog } from "../components/LinkDialog";
import { userEditSchema, type UserEditForm } from "../schemas";

type Action = "revoke" | "mfa" | null;

export function UserDetailPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { userId = "" } = useParams();
  const user = useQuery({
    queryKey: ["admin", "users", userId],
    queryFn: () => adminApi.user(userId),
  });
  const key = useRef(newIdempotencyKey());
  const [link, setLink] = useState<Link | null>(null);
  const [confirm, setConfirm] = useState<Action>(null);
  const form = useForm<UserEditForm>({ resolver: zodResolver(userEditSchema), mode: "onBlur" });
  useUnsavedChangesWarning(form.formState.isDirty);

  useEffect(() => {
    if (user.data !== undefined) {
      form.reset({
        username: user.data.username,
        email: user.data.email ?? "",
        display_name: user.data.display_name ?? "",
        role: user.data.role,
        status: user.data.status,
      });
    }
  }, [user.data, form]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
  const save = useMutation({
    mutationFn: (values: UserEditForm) =>
      adminApi.updateUser(
        userId,
        {
          email: values.email || null,
          display_name: values.display_name || null,
          role: values.role,
          status: values.status,
        },
        key.current,
      ),
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      toast(t("common.saved"));
      await refresh();
    },
  });
  const resetLink = useMutation({
    mutationFn: () => adminApi.resetLink(userId),
    onSuccess: setLink,
  });
  const revoke = useMutation({
    mutationFn: () => adminApi.revokeSessions(userId),
    onSuccess: async (result) => {
      setConfirm(null);
      toast(t("account.sessionsRevoked", { count: result.count }));
      await refresh();
    },
  });
  const resetMfa = useMutation({
    mutationFn: () => adminApi.resetMfa(userId),
    onSuccess: async () => {
      setConfirm(null);
      toast(t("admin.mfaReset"));
      await refresh();
    },
  });

  if (user.isError) return <ErrorState error={user.error} onRetry={() => void user.refetch()} />;
  if (user.data === undefined) return <Skeleton className="h-64 w-full max-w-xl" />;
  const data = user.data;
  const message = (value: string | undefined) => (value !== undefined ? t(value) : undefined);

  return (
    <div className="mx-auto max-w-(--content-max-width)">
      <PageHeader
        title={data.username}
        breadcrumb={[
          { label: t("nav.home"), to: "/" },
          { label: t("admin.users"), to: "/admin/users" },
          { label: data.username },
        ]}
      />
      <div className="mb-6 flex flex-wrap gap-2">
        <Badge tone={data.status === "active" ? "success" : "danger"}>
          {t(`status.${data.status}`)}
        </Badge>
        <Badge tone={data.mfa_enrolled ? "success" : "neutral"}>
          {data.mfa_enrolled ? t("admin.mfaOn") : t("admin.mfaOff")}
        </Badge>
        <Badge>{t("admin.activeSessions", { count: data.active_sessions })}</Badge>
        <Badge>{t("admin.lastLoginAt", { date: formatDateTime(data.last_login_at) })}</Badge>
      </div>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,32rem)_1fr]">
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) =>
            void form.handleSubmit((values) => {
              save.mutate(values);
            })(event)
          }
        >
          <TextField label={t("auth.username")} disabled {...form.register("username")} />
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
          <SelectField
            label={t("admin.status")}
            options={[
              { value: "active", label: t("status.active") },
              { value: "disabled", label: t("status.disabled") },
            ]}
            {...form.register("status")}
          />
          <FormError error={save.error} />
          <div className="flex gap-2">
            <Button
              type="submit"
              variant="primary"
              loading={save.isPending}
              disabled={!form.formState.isDirty}
            >
              {t("common.save")}
            </Button>
            <Button
              disabled={!form.formState.isDirty}
              onClick={() => {
                form.reset();
              }}
            >
              {t("common.cancel")}
            </Button>
          </div>
        </form>
        <aside className="space-y-4">
          <section className="space-y-2">
            <h2 className="font-semibold">{t("admin.groups")}</h2>
            <p className="text-text-muted">
              {data.groups.length > 0
                ? data.groups.map((g) => g.name).join(", ")
                : t("admin.noGroups")}
            </p>
          </section>
          <section className="space-y-2">
            <h2 className="font-semibold">{t("admin.accountActions")}</h2>
            <div className="flex flex-col items-start gap-2">
              <Button
                loading={resetLink.isPending}
                onClick={() => {
                  resetLink.mutate();
                }}
              >
                {t("admin.createResetLink")}
              </Button>
              <Button
                onClick={() => {
                  setConfirm("revoke");
                }}
              >
                {t("admin.revokeSessions")}
              </Button>
              <Button
                variant="danger"
                disabled={!data.mfa_enrolled}
                onClick={() => {
                  setConfirm("mfa");
                }}
              >
                {t("admin.resetMfa")}
              </Button>
            </div>
            <FormError error={resetLink.error ?? revoke.error ?? resetMfa.error} />
          </section>
        </aside>
      </div>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={
          confirm === "mfa"
            ? t("admin.confirmResetMfa", { name: data.username })
            : t("admin.confirmRevoke", { name: data.username })
        }
        description={
          confirm === "mfa" ? t("admin.confirmResetMfaHelp") : t("admin.confirmRevokeHelp")
        }
        confirmLabel={confirm === "mfa" ? t("admin.resetMfa") : t("admin.revokeSessions")}
        loading={revoke.isPending || resetMfa.isPending}
        onConfirm={() => {
          if (confirm === "mfa") resetMfa.mutate();
          else revoke.mutate();
        }}
      />
      <LinkDialog
        link={link}
        title={t("admin.resetLink")}
        onClose={() => {
          setLink(null);
        }}
      />
    </div>
  );
}
