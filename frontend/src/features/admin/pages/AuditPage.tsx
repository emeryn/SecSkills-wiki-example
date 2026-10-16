import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Download, ScrollText } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { DataTable, Pagination } from "../../../components/ui/DataTable";
import { Dialog } from "../../../components/ui/Dialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { useToast } from "../../../components/ui/Toast";
import { saveBlob } from "../../../lib/download";
import { formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { operationsApi, type AuditEvent } from "../api";

const DEFAULTS = {
  action: "",
  actor: "",
  outcome: "",
  severity: "",
  ip: "",
  start: "",
  end: "",
  page: "1",
};
const ALLOWED = {
  outcome: ["", "success", "failure"],
  severity: ["", "info", "warning", "critical"],
} as const;
const PAGE_SIZE = 50;
const SELECT = "h-9 rounded-md border border-border bg-surface px-2";

/** Local calendar day (yyyy-mm-dd) of an ISO instant, for the date inputs. */
function day(iso: string): string {
  if (iso === "") return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function startOf(value: string, nextDay = false): string {
  if (value === "") return "";
  const date = new Date(`${value}T00:00:00`);
  if (nextDay) date.setDate(date.getDate() + 1);
  return date.toISOString();
}

function filters(state: typeof DEFAULTS): Record<string, string | undefined> {
  return Object.fromEntries(
    Object.entries(state).filter(([name, value]) => name !== "page" && value !== ""),
  );
}

/** Scheduled jobs and the CLI record "system"; requests before sign-in have no actor. */
function actorName(event: AuditEvent, systemLabel: string): string {
  if (event.actor.username !== null) return event.actor.username;
  return event.user_agent === "system" ? systemLabel : "—";
}

function EventDetails({ event, onClose }: { event: AuditEvent | null; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={event !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={event?.action ?? ""}
      size="lg"
    >
      {event !== null && (
        <div className="space-y-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
            <dt className="text-text-muted">{t("audit.time")}</dt>
            <dd>{formatDateTime(event.occurred_at)}</dd>
            <dt className="text-text-muted">{t("audit.actor")}</dt>
            <dd>{actorName(event, t("audit.system"))}</dd>
            <dt className="text-text-muted">{t("audit.ip")}</dt>
            <dd className="font-mono">{event.actor_ip ?? "—"}</dd>
            <dt className="text-text-muted">{t("audit.userAgent")}</dt>
            <dd className="break-all">{event.user_agent || "—"}</dd>
            <dt className="text-text-muted">{t("audit.target")}</dt>
            <dd className="font-mono">
              {event.target_type !== null ? `${event.target_type}:${event.target_id ?? ""}` : "—"}
            </dd>
            <dt className="text-text-muted">{t("audit.requestId")}</dt>
            <dd className="font-mono text-xs">{event.request_id ?? "—"}</dd>
          </dl>
          {(["before", "after"] as const).map((key) =>
            event[key] !== null ? (
              <div key={key}>
                <p className="font-medium">{t(`audit.${key}`)}</p>
                {/* Rendered as text: React escapes it, nothing is interpreted as markup. */}
                <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-surface-muted p-3 font-mono text-xs break-all whitespace-pre-wrap">
                  {JSON.stringify(event[key], null, 2)}
                </pre>
              </div>
            ) : null,
          )}
        </div>
      )}
    </Dialog>
  );
}

export function AuditPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const [state, update] = useUrlState(DEFAULTS, ALLOWED);
  const [actor, setActor] = useState(state.actor);
  const [ip, setIp] = useState(state.ip);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const page = Math.max(1, Number.parseInt(state.page, 10) || 1);

  const events = useQuery({
    queryKey: ["admin", "audit", state],
    queryFn: () => operationsApi.audit({ ...filters(state), page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const actions = useQuery({
    queryKey: ["admin", "audit", "actions"],
    queryFn: operationsApi.auditActions,
  });
  const exportCsv = useMutation({
    mutationFn: () => operationsApi.auditExport(filters(state)),
    onSuccess: ({ blob, filename }) => {
      saveBlob(blob, filename);
      toast(t("audit.exported"));
    },
  });

  return (
    <>
      <PageHeader
        title={t("audit.title")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("audit.title") }]}
        primaryAction={
          <Button
            variant="primary"
            icon={<Download aria-hidden className="size-4" />}
            loading={exportCsv.isPending}
            onClick={() => {
              exportCsv.mutate();
            }}
          >
            {t("audit.exportCsv")}
          </Button>
        }
      />
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          update({ actor: actor.trim(), ip: ip.trim() });
        }}
      >
        <select
          aria-label={t("audit.action")}
          value={state.action}
          onChange={(event) => {
            update({ action: event.target.value });
          }}
          className={SELECT}
        >
          <option value="">{t("audit.allActions")}</option>
          {(actions.data ?? []).map((action) => (
            <option key={action} value={action}>
              {action}
            </option>
          ))}
          {state.action !== "" && !(actions.data ?? []).includes(state.action) && (
            <option value={state.action}>{state.action}</option>
          )}
        </select>
        <select
          aria-label={t("audit.outcome")}
          value={state.outcome}
          onChange={(event) => {
            update({ outcome: event.target.value });
          }}
          className={SELECT}
        >
          <option value="">{t("audit.allOutcomes")}</option>
          <option value="success">{t("audit.outcomes.success")}</option>
          <option value="failure">{t("audit.outcomes.failure")}</option>
        </select>
        <select
          aria-label={t("audit.severityLabel")}
          value={state.severity}
          onChange={(event) => {
            update({ severity: event.target.value });
          }}
          className={SELECT}
        >
          <option value="">{t("audit.allSeverities")}</option>
          {(["info", "warning", "critical"] as const).map((value) => (
            <option key={value} value={value}>
              {t(`audit.severity.${value}`)}
            </option>
          ))}
        </select>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-muted">{t("audit.from")}</span>
          <input
            type="date"
            value={day(state.start)}
            onChange={(event) => {
              update({ start: startOf(event.target.value) });
            }}
            className={SELECT}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-muted">{t("audit.to")}</span>
          <input
            type="date"
            value={state.end === "" ? "" : day(new Date(Date.parse(state.end) - 1).toISOString())}
            onChange={(event) => {
              update({ end: startOf(event.target.value, true) });
            }}
            className={SELECT}
          />
        </label>
        <input
          aria-label={t("audit.actor")}
          placeholder={t("audit.actorPlaceholder")}
          value={actor}
          maxLength={64}
          onChange={(event) => {
            setActor(event.target.value);
          }}
          className={`${SELECT} w-40`}
        />
        <input
          aria-label={t("audit.ip")}
          placeholder={t("audit.ip")}
          value={ip}
          maxLength={45}
          onChange={(event) => {
            setIp(event.target.value);
          }}
          className={`${SELECT} w-40`}
        />
        <Button type="submit">{t("audit.apply")}</Button>
      </form>
      <div className="mb-3">
        <FormError error={exportCsv.error} />
      </div>
      {events.isError ? (
        <ErrorState error={events.error} onRetry={() => void events.refetch()} />
      ) : (
        <>
          <DataTable<AuditEvent>
            caption={t("audit.title")}
            loading={events.isPending}
            rows={events.data?.items}
            rowKey={(row) => String(row.id)}
            onRowClick={setSelected}
            empty={
              <EmptyState
                icon={ScrollText}
                title={t("audit.empty")}
                description={t("audit.emptyHelp")}
              />
            }
            columns={[
              {
                key: "time",
                header: t("audit.time"),
                render: (row) => formatDateTime(row.occurred_at),
              },
              {
                key: "actor",
                header: t("audit.actor"),
                render: (row) => actorName(row, t("audit.system")),
              },
              {
                key: "action",
                header: t("audit.action"),
                render: (row) => <span className="font-mono">{row.action}</span>,
              },
              {
                key: "outcome",
                header: t("audit.outcome"),
                render: (row) => (
                  <Badge tone={row.outcome === "success" ? "neutral" : "danger"}>
                    {t(`audit.outcomes.${row.outcome}`)}
                  </Badge>
                ),
              },
              {
                key: "severity",
                header: t("audit.severityLabel"),
                render: (row) =>
                  row.severity === "info" ? (
                    t("audit.severity.info")
                  ) : (
                    <Badge tone="danger">{t(`audit.severity.${row.severity}`)}</Badge>
                  ),
              },
              {
                key: "target",
                header: t("audit.target"),
                render: (row) =>
                  row.target_type !== null ? `${row.target_type}:${row.target_id ?? ""}` : "—",
              },
              {
                key: "ip",
                header: t("audit.ip"),
                render: (row) => <span className="font-mono">{row.actor_ip ?? "—"}</span>,
              },
            ]}
          />
          {events.data !== undefined && events.data.total > 0 && (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={events.data.total}
              onPage={(next) => {
                update({ page: String(next) }, { resetPage: false });
              }}
            />
          )}
        </>
      )}
      <EventDetails
        event={selected}
        onClose={() => {
          setSelected(null);
        }}
      />
    </>
  );
}
