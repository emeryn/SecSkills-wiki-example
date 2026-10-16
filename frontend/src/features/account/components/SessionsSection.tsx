import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { useToast } from "../../../components/ui/Toast";
import { formatDateTime } from "../../../lib/format";
import { accountApi, type SessionSummary } from "../api";
import { MonitorSmartphone } from "lucide-react";

const SESSIONS_KEY = ["account", "sessions"] as const;

export function SessionsSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: SESSIONS_KEY, queryFn: accountApi.sessions });
  const refresh = () => queryClient.invalidateQueries({ queryKey: SESSIONS_KEY });
  const revoke = useMutation({
    mutationFn: accountApi.revokeSession,
    onSuccess: async () => {
      toast(t("account.sessionRevoked"));
      await refresh();
    },
  });
  const revokeOthers = useMutation({
    mutationFn: accountApi.revokeOtherSessions,
    onSuccess: async (result) => {
      toast(t("account.sessionsRevoked", { count: result.count }));
      await refresh();
    },
  });

  if (sessions.isError)
    return <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />;
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          loading={revokeOthers.isPending}
          onClick={() => {
            revokeOthers.mutate();
          }}
        >
          {t("account.signOutOthers")}
        </Button>
      </div>
      <FormError error={revoke.error ?? revokeOthers.error} />
      <DataTable<SessionSummary>
        caption={t("account.sessions")}
        loading={sessions.isPending}
        rows={sessions.data}
        rowKey={(row) => row.id}
        empty={
          <EmptyState
            icon={MonitorSmartphone}
            title={t("account.sessions")}
            description={t("account.noSessions")}
          />
        }
        columns={[
          {
            key: "device",
            header: t("account.device"),
            render: (row) => (
              <span className="flex items-center gap-2">
                <span className="max-w-xs truncate" title={row.user_agent}>
                  {row.user_agent || "—"}
                </span>
                {row.current && <Badge tone="primary">{t("account.thisDevice")}</Badge>}
              </span>
            ),
          },
          { key: "ip", header: t("account.ipAddress"), render: (row) => row.ip ?? "—" },
          {
            key: "last_seen",
            header: t("account.lastActive"),
            render: (row) => formatDateTime(row.last_seen_at),
          },
          {
            key: "created",
            header: t("account.signedIn"),
            render: (row) => formatDateTime(row.created_at),
          },
          {
            key: "actions",
            header: "",
            render: (row) =>
              row.current ? null : (
                <Button
                  variant="ghost"
                  onClick={() => {
                    revoke.mutate(row.id);
                  }}
                >
                  {t("account.signOut")}
                </Button>
              ),
          },
        ]}
      />
    </div>
  );
}
