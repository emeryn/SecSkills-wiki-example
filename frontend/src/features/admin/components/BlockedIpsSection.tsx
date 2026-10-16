import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { useToast } from "../../../components/ui/Toast";
import { formatDateTime } from "../../../lib/format";
import { operationsApi, type BlockedIp } from "../api";

/** Client IPs blocked by honeytokens, with unblocking. */
export function BlockedIpsSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<BlockedIp | null>(null);
  const blocked = useQuery({
    queryKey: ["admin", "blocked-ips"],
    queryFn: operationsApi.blockedIps,
  });
  const unblock = useMutation({
    mutationFn: (ip: string) => operationsApi.unblock(ip),
    onSuccess: async () => {
      setTarget(null);
      toast(t("settings.unblocked"));
      await queryClient.invalidateQueries({ queryKey: ["admin", "blocked-ips"] });
    },
  });

  return (
    <section className="mt-10 max-w-3xl space-y-3">
      <h2 className="text-lg font-semibold">{t("settings.blockedIps")}</h2>
      {blocked.isError ? (
        <ErrorState error={blocked.error} onRetry={() => void blocked.refetch()} />
      ) : (
        <DataTable<BlockedIp>
          caption={t("settings.blockedIps")}
          loading={blocked.isPending}
          rows={blocked.data}
          rowKey={(row) => row.ip}
          empty={
            <EmptyState
              icon={ShieldCheck}
              title={t("settings.noBlockedIps")}
              description={t("settings.noBlockedIpsHelp")}
            />
          }
          columns={[
            {
              key: "ip",
              header: t("audit.ip"),
              render: (row) => <span className="font-mono">{row.ip}</span>,
            },
            {
              key: "reason",
              header: t("settings.reason"),
              render: (row) => t(`settings.reasons.${row.reason}`, row.reason),
            },
            { key: "hits", header: t("settings.hits"), render: (row) => row.hits },
            {
              key: "blocked_at",
              header: t("settings.blockedAt"),
              render: (row) => formatDateTime(row.blocked_at),
            },
            {
              key: "expires_at",
              header: t("settings.expiresAt"),
              render: (row) =>
                row.expires_at !== null
                  ? formatDateTime(row.expires_at)
                  : t("settings.untilUnblocked"),
            },
            {
              key: "actions",
              header: t("pages.actions"),
              render: (row) => (
                <Button
                  onClick={() => {
                    setTarget(row);
                  }}
                >
                  {t("settings.unblock")}
                </Button>
              ),
            },
          ]}
        />
      )}
      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) setTarget(null);
        }}
        title={t("settings.confirmUnblock", { ip: target?.ip ?? "" })}
        description={t("settings.confirmUnblockHelp")}
        confirmLabel={t("settings.unblock")}
        loading={unblock.isPending}
        onConfirm={() => {
          if (target !== null) unblock.mutate(target.ip);
        }}
      />
    </section>
  );
}
