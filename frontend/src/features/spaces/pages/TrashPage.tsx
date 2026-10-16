import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { useToast } from "../../../components/ui/Toast";
import { formatDateTime } from "../../../lib/format";
import { canRole, spaceKeys, spacesApi, type TrashItem } from "../api";
import { useSpaceContext } from "./SpaceLayout";

export function TrashPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { space } = useSpaceContext();
  const trash = useQuery({
    queryKey: spaceKeys.trash(space.key),
    queryFn: () => spacesApi.trash(space.key),
  });
  const [purging, setPurging] = useState<TrashItem | null>(null);
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: spaceKeys.trash(space.key) });
    await queryClient.invalidateQueries({ queryKey: spaceKeys.tree(space.key) });
  };
  const restore = useMutation({
    mutationFn: (item: TrashItem) => spacesApi.restore(space.key, item.id),
    onSuccess: async () => {
      toast(t("trash.restored"));
      await refresh();
    },
  });
  const purge = useMutation({
    mutationFn: (item: TrashItem) => spacesApi.purge(space.key, item.id),
    onSuccess: async () => {
      setPurging(null);
      toast(t("trash.purged"));
      await refresh();
    },
  });
  const canPurge = canRole(space.role, "space_admin");

  return (
    <>
      <PageHeader
        title={t("trash.title")}
        breadcrumb={[
          { label: space.name, to: `/spaces/${space.key}` },
          { label: t("trash.title") },
        ]}
      />
      <p className="mb-4 text-text-muted">{t("trash.help")}</p>
      <FormError error={restore.error ?? purge.error} />
      {trash.isError ? (
        <ErrorState error={trash.error} onRetry={() => void trash.refetch()} />
      ) : (
        <DataTable<TrashItem>
          caption={t("trash.title")}
          loading={trash.isPending}
          rows={trash.data}
          rowKey={(row) => row.id}
          empty={
            <EmptyState icon={Trash2} title={t("trash.empty")} description={t("trash.emptyHelp")} />
          }
          columns={[
            {
              key: "title",
              header: t("pages.pageTitle"),
              render: (row) => <span className="font-medium">{row.title}</span>,
            },
            { key: "pages", header: t("trash.pages"), render: (row) => row.pages },
            {
              key: "deleted",
              header: t("trash.deleted"),
              render: (row) => `${formatDateTime(row.deleted_at)} · ${row.deleted_by ?? "—"}`,
            },
            {
              key: "purge",
              header: t("trash.purgeAfter"),
              render: (row) => formatDateTime(row.purge_after),
            },
            {
              key: "actions",
              header: "",
              render: (row) => (
                <span className="flex gap-1">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      restore.mutate(row);
                    }}
                  >
                    {t("trash.restore")}
                  </Button>
                  {canPurge && (
                    <Button
                      variant="ghost"
                      className="text-danger"
                      onClick={() => {
                        setPurging(row);
                      }}
                    >
                      {t("trash.purge")}
                    </Button>
                  )}
                </span>
              ),
            },
          ]}
        />
      )}
      <ConfirmDialog
        open={purging !== null}
        onOpenChange={(open) => {
          if (!open) setPurging(null);
        }}
        title={t("trash.confirmPurge", { title: purging?.title ?? "" })}
        description={t("trash.confirmPurgeHelp")}
        confirmLabel={t("trash.purge")}
        loading={purge.isPending}
        onConfirm={() => {
          if (purging !== null) purge.mutate(purging);
        }}
      />
    </>
  );
}
