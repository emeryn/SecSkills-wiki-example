import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { formatBytes, formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { operationsApi, type Dashboard, type Period } from "../api";
import { ActivityChart } from "../components/ActivityChart";

const PERIODS: readonly Period[] = ["24h", "7d", "30d"];
const DEFAULTS = { period: "7d" };
const ALLOWED = { period: PERIODS };

function Kpi({
  label,
  value,
  to,
  hint,
}: {
  label: string;
  value: ReactNode;
  to: string;
  hint?: string;
}) {
  return (
    <Link
      to={to}
      className="block rounded-lg border border-border p-4 hover:border-primary hover:bg-surface-muted"
    >
      <p className="text-text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint !== undefined && <p className="mt-1 text-xs text-text-muted">{hint}</p>}
    </Link>
  );
}

function auditLink(params: Record<string, string>): string {
  return `/admin/audit?${new URLSearchParams(params).toString()}`;
}

function Kpis({ data }: { data: Dashboard }) {
  const { t } = useTranslation();
  const since = data.since;
  const backupFresh = !data.backup.overdue;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi
        label={t("adminDashboard.activeUsers")}
        value={data.users.active}
        to="/admin/users?status=active"
        hint={t("adminDashboard.signedIn", { count: data.users.signed_in })}
      />
      <Kpi
        label={t("adminDashboard.pages")}
        value={data.content.pages}
        to="/admin/spaces"
        hint={t("adminDashboard.edits", { count: data.content.revisions })}
      />
      <Kpi
        label={t("adminDashboard.failedSignIns")}
        value={data.security.failed_sign_ins}
        to={auditLink({ action: "auth.login", outcome: "failure", start: since })}
      />
      <Kpi
        label={t("adminDashboard.honeytokenAlerts")}
        value={data.security.honeytoken_alerts}
        to={auditLink({ action: "security.honeytoken", start: since })}
        hint={t("adminDashboard.blockedIps", { count: data.security.blocked_ips })}
      />
      <Kpi label={t("adminDashboard.serverErrors")} value={data.errors.count} to="#recent-errors" />
      <Kpi
        label={t("adminDashboard.attachments")}
        value={data.content.attachments}
        to="/admin/spaces"
        hint={formatBytes(data.content.attachment_bytes)}
      />
      <Kpi
        label={t("adminDashboard.lastBackup")}
        value={
          <Badge tone={backupFresh ? "success" : "danger"}>
            {backupFresh ? t("adminDashboard.backupOk") : t("adminDashboard.backupMissing")}
          </Badge>
        }
        to={auditLink({ action: "backup.created" })}
        hint={
          data.backup.last_at !== null
            ? `${formatDateTime(data.backup.last_at)} · ${formatBytes(data.backup.size_bytes)}`
            : t("adminDashboard.noBackup")
        }
      />
      <Kpi
        label={t("adminDashboard.spaces")}
        value={data.content.spaces}
        to="/admin/spaces"
        hint={t("adminDashboard.usersTotal", { count: data.users.total })}
      />
    </div>
  );
}

function Alerts({ data }: { data: Dashboard }) {
  const { t } = useTranslation();
  if (data.alerts.length === 0) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title={t("adminDashboard.noAlerts")}
        description={t("adminDashboard.noAlertsHelp")}
      />
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {data.alerts.map((alert) => (
        <li key={alert.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
          <Badge tone="danger">{t("audit.severity.critical")}</Badge>
          <span className="font-mono">{alert.actor_ip ?? "—"}</span>
          <span className="text-text-muted">
            {typeof alert.after?.kind === "string" ? alert.after.kind : ""}
          </span>
          <span className="ml-auto text-text-muted">{formatDateTime(alert.occurred_at)}</span>
        </li>
      ))}
    </ul>
  );
}

function RecentErrors({ data }: { data: Dashboard }) {
  const { t } = useTranslation();
  if (data.errors.recent.length === 0) {
    return <p className="text-text-muted">{t("adminDashboard.noErrors")}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left">
        <caption className="sr-only">{t("adminDashboard.recentErrors")}</caption>
        <thead className="bg-surface-muted text-xs text-text-muted uppercase">
          <tr>
            <th scope="col" className="px-3 py-2">
              {t("audit.time")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("adminDashboard.request")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("admin.status")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("audit.requestId")}
            </th>
          </tr>
        </thead>
        <tbody>
          {data.errors.recent.map((error) => (
            <tr key={error.id} className="border-t border-border">
              <td className="px-3 py-2">{formatDateTime(error.occurred_at)}</td>
              <td className="px-3 py-2 font-mono">{`${error.method} ${error.path}`}</td>
              <td className="px-3 py-2">{error.status}</td>
              <td className="px-3 py-2 font-mono text-xs">{error.request_id ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Usage, errors, security alerts and backups; every number links to the filtered list. */
export function AdminDashboardPage() {
  const { t } = useTranslation();
  const [state, update] = useUrlState(DEFAULTS, ALLOWED);
  const period = state.period as Period;
  const dashboard = useQuery({
    queryKey: ["admin", "dashboard", period],
    queryFn: () => operationsApi.dashboard(period),
    placeholderData: keepPreviousData,
  });
  const hourly = period === "24h";

  return (
    <>
      <PageHeader
        title={t("adminDashboard.title")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("adminDashboard.title") }]}
        secondaryActions={
          <div role="group" aria-label={t("adminDashboard.period")} className="flex gap-1">
            {PERIODS.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={period === value}
                onClick={() => {
                  update({ period: value });
                }}
                className="h-9 rounded-md border border-border px-3 aria-pressed:border-primary aria-pressed:bg-primary/10 aria-pressed:text-primary"
              >
                {t(`adminDashboard.periods.${value}`)}
              </button>
            ))}
          </div>
        }
      />
      {dashboard.isError ? (
        <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : dashboard.data === undefined ? (
        <div aria-busy className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
          <span className="sr-only">{t("common.loading")}</span>
        </div>
      ) : (
        <div className="space-y-8">
          <Kpis data={dashboard.data} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ActivityChart
              title={t("adminDashboard.signInsChart")}
              hourly={hourly}
              points={dashboard.data.activity.map((p) => ({ bucket: p.bucket, value: p.sign_ins }))}
            />
            <ActivityChart
              title={t("adminDashboard.editsChart")}
              hourly={hourly}
              points={dashboard.data.activity.map((p) => ({ bucket: p.bucket, value: p.edits }))}
            />
          </div>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">{t("adminDashboard.securityAlerts")}</h2>
            <Alerts data={dashboard.data} />
          </section>
          <section id="recent-errors" className="space-y-3">
            <h2 className="text-lg font-semibold">{t("adminDashboard.recentErrors")}</h2>
            <RecentErrors data={dashboard.data} />
          </section>
        </div>
      )}
    </>
  );
}
