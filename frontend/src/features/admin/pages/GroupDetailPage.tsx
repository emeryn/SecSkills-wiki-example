import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { ErrorState } from "../../../components/ui/ErrorState";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { useUnsavedChangesWarning } from "../../../lib/unsaved-changes";
import { adminApi } from "../api";
import { groupFormSchema, type GroupForm } from "../schemas";

export function GroupDetailPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { groupId = "" } = useParams();
  const group = useQuery({
    queryKey: ["admin", "groups", groupId],
    queryFn: () => adminApi.group(groupId),
  });
  const key = useRef(newIdempotencyKey());
  const [memberQuery, setMemberQuery] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const form = useForm<GroupForm>({ resolver: zodResolver(groupFormSchema), mode: "onBlur" });
  useUnsavedChangesWarning(form.formState.isDirty);

  useEffect(() => {
    if (group.data !== undefined)
      form.reset({ name: group.data.name, description: group.data.description });
  }, [group.data, form]);

  const candidates = useQuery({
    queryKey: ["admin", "users", { q: memberQuery }],
    queryFn: () => adminApi.users({ q: memberQuery, page_size: 10 }),
    enabled: memberQuery.trim().length >= 2,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "groups"] });
  const save = useMutation({
    mutationFn: (values: GroupForm) => adminApi.updateGroup(groupId, values, key.current),
    onSuccess: async () => {
      key.current = newIdempotencyKey();
      toast(t("common.saved"));
      await refresh();
    },
  });
  const add = useMutation({
    mutationFn: (userId: string) => adminApi.addMember(groupId, userId),
    onSuccess: async () => {
      setMemberQuery("");
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => adminApi.removeMember(groupId, userId),
    onSuccess: refresh,
  });
  const destroy = useMutation({
    mutationFn: () => adminApi.deleteGroup(groupId),
    onSuccess: async () => {
      form.reset(form.getValues());
      toast(t("admin.groupDeleted"));
      await refresh();
      await navigate("/admin/groups");
    },
  });

  if (group.isError) return <ErrorState error={group.error} onRetry={() => void group.refetch()} />;
  if (group.data === undefined) return <Skeleton className="h-64 w-full max-w-xl" />;
  const data = group.data;
  const memberIds = new Set(data.members.map((m) => m.id));
  const message = (value: string | undefined) => (value !== undefined ? t(value) : undefined);

  return (
    <div className="mx-auto max-w-(--content-max-width)">
      <PageHeader
        title={data.name}
        breadcrumb={[
          { label: t("nav.home"), to: "/" },
          { label: t("admin.groups"), to: "/admin/groups" },
          { label: data.name },
        ]}
        secondaryActions={
          <Button
            variant="ghost"
            icon={<Trash2 aria-hidden className="size-4" />}
            onClick={() => {
              setConfirmDelete(true);
            }}
          >
            {t("common.delete")}
          </Button>
        }
      />
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
          <TextField
            label={t("admin.groupName")}
            required
            error={message(form.formState.errors.name?.message)}
            {...form.register("name")}
          />
          <TextField
            label={t("admin.description")}
            error={message(form.formState.errors.description?.message)}
            {...form.register("description")}
          />
          <FormError error={save.error} />
          <Button
            type="submit"
            variant="primary"
            loading={save.isPending}
            disabled={!form.formState.isDirty}
          >
            {t("common.save")}
          </Button>
        </form>
        <section className="space-y-3">
          <h2 className="font-semibold">
            {t("admin.membersCount", { count: data.members.length })}
          </h2>
          <div className="space-y-2">
            <label htmlFor="member-search" className="block font-medium">
              {t("admin.addMember")}
            </label>
            <input
              id="member-search"
              type="search"
              value={memberQuery}
              placeholder={t("admin.searchUsers")}
              onChange={(event) => {
                setMemberQuery(event.target.value);
              }}
              className="h-9 w-full max-w-sm rounded-md border border-border bg-surface px-3"
            />
            {candidates.data !== undefined && memberQuery.trim().length >= 2 && (
              <ul className="max-w-sm divide-y divide-border rounded-md border border-border">
                {candidates.data.items
                  .filter((u) => !memberIds.has(u.id))
                  .map((u) => (
                    <li key={u.id} className="flex items-center justify-between px-3 py-1.5">
                      <span>{u.username}</span>
                      <Button
                        variant="ghost"
                        aria-label={t("admin.addUser", { name: u.username })}
                        icon={<UserPlus aria-hidden className="size-4" />}
                        onClick={() => {
                          add.mutate(u.id);
                        }}
                      />
                    </li>
                  ))}
              </ul>
            )}
          </div>
          <FormError error={add.error ?? remove.error} />
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.members.length === 0 && (
              <li className="px-3 py-2 text-text-muted">{t("admin.noMembers")}</li>
            )}
            {data.members.map((member) => (
              <li key={member.id} className="flex items-center justify-between px-3 py-2">
                <span>
                  <span className="font-medium">{member.username}</span>
                  {member.display_name !== null && (
                    <span className="text-text-muted"> · {member.display_name}</span>
                  )}
                </span>
                <Button
                  variant="ghost"
                  aria-label={t("admin.removeMember", { name: member.username })}
                  icon={<Trash2 aria-hidden className="size-4" />}
                  onClick={() => {
                    remove.mutate(member.id);
                  }}
                />
              </li>
            ))}
          </ul>
        </section>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("admin.confirmDeleteGroup", { name: data.name })}
        description={t("admin.confirmDeleteGroupHelp")}
        confirmLabel={t("common.delete")}
        loading={destroy.isPending}
        onConfirm={() => {
          destroy.mutate();
        }}
      />
      <FormError error={destroy.error} />
    </div>
  );
}
