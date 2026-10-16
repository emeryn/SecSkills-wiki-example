import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { DataTable, Pagination } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { adminApi, type AdminUser, type Link } from "../api";
import { CreateUserDialog } from "../components/CreateUserDialog";
import { LinkDialog } from "../components/LinkDialog";

const DEFAULTS = { q: "", role: "", status: "", sort: "username", order: "asc", page: "1" };
const ALLOWED = {
  role: ["", "user", "admin"],
  status: ["", "active", "disabled"],
  sort: ["username", "created_at", "last_login_at"],
  order: ["asc", "desc"],
} as const;
const PAGE_SIZE = 25;

export function UsersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [state, update] = useUrlState(DEFAULTS, ALLOWED);
  const [search, setSearch] = useState(state.q);
  const [creating, setCreating] = useState(false);
  const [invitation, setInvitation] = useState<Link | null>(null);
  const page = Math.max(1, Number.parseInt(state.page, 10) || 1);

  const users = useQuery({
    queryKey: ["admin", "users", state],
    queryFn: () => adminApi.users({ ...state, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title={t("admin.users")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("admin.users") }]}
        primaryAction={
          <Button
            variant="primary"
            icon={<Plus aria-hidden className="size-4" />}
            onClick={() => {
              setCreating(true);
            }}
          >
            {t("admin.newUser")}
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <form
          role="search"
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            update({ q: search.trim() });
          }}
        >
          <label htmlFor="user-search" className="sr-only">
            {t("admin.searchUsers")}
          </label>
          <input
            id="user-search"
            type="search"
            value={search}
            placeholder={t("admin.searchUsers")}
            onChange={(event) => {
              setSearch(event.target.value);
            }}
            className="h-9 w-64 rounded-md border border-border bg-surface px-3"
          />
          <Button
            type="submit"
            aria-label={t("common.search")}
            icon={<Search aria-hidden className="size-4" />}
          />
        </form>
        <select
          aria-label={t("account.role")}
          value={state.role}
          onChange={(event) => {
            update({ role: event.target.value });
          }}
          className="h-9 rounded-md border border-border bg-surface px-2"
        >
          <option value="">{t("admin.allRoles")}</option>
          <option value="user">{t("roles.user")}</option>
          <option value="admin">{t("roles.admin")}</option>
        </select>
        <select
          aria-label={t("admin.status")}
          value={state.status}
          onChange={(event) => {
            update({ status: event.target.value });
          }}
          className="h-9 rounded-md border border-border bg-surface px-2"
        >
          <option value="">{t("admin.allStatuses")}</option>
          <option value="active">{t("status.active")}</option>
          <option value="disabled">{t("status.disabled")}</option>
        </select>
      </div>

      {users.isError ? (
        <ErrorState error={users.error} onRetry={() => void users.refetch()} />
      ) : (
        <>
          <DataTable<AdminUser>
            caption={t("admin.users")}
            loading={users.isPending}
            rows={users.data?.items}
            rowKey={(row) => row.id}
            sort={state.sort}
            order={state.order === "desc" ? "desc" : "asc"}
            onSort={(key) => {
              update({
                sort: key,
                order: state.sort === key && state.order === "asc" ? "desc" : "asc",
              });
            }}
            onRowClick={(row) => void navigate(`/admin/users/${row.id}`)}
            empty={
              <EmptyState
                icon={Users}
                title={t("admin.noUsers")}
                description={t("admin.noUsersHelp")}
                action={
                  <Button
                    variant="primary"
                    onClick={() => {
                      setCreating(true);
                    }}
                  >
                    {t("admin.newUser")}
                  </Button>
                }
              />
            }
            columns={[
              {
                key: "username",
                header: t("auth.username"),
                sortable: true,
                render: (row) => <span className="font-medium">{row.username}</span>,
              },
              {
                key: "display_name",
                header: t("account.displayName"),
                render: (row) => row.display_name ?? "—",
              },
              { key: "email", header: t("auth.email"), render: (row) => row.email ?? "—" },
              {
                key: "role",
                header: t("account.role"),
                render: (row) => (
                  <Badge tone={row.role === "admin" ? "primary" : "neutral"}>
                    {t(`roles.${row.role}`)}
                  </Badge>
                ),
              },
              {
                key: "status",
                header: t("admin.status"),
                render: (row) => (
                  <Badge tone={row.status === "active" ? "success" : "danger"}>
                    {t(`status.${row.status}`)}
                  </Badge>
                ),
              },
              {
                key: "last_login_at",
                header: t("admin.lastLogin"),
                sortable: true,
                render: (row) => formatDateTime(row.last_login_at),
              },
            ]}
          />
          {users.data !== undefined && users.data.total > 0 && (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={users.data.total}
              onPage={(next) => {
                update({ page: String(next) }, { resetPage: false });
              }}
            />
          )}
        </>
      )}
      <CreateUserDialog open={creating} onOpenChange={setCreating} onCreated={setInvitation} />
      <LinkDialog
        link={invitation}
        title={t("admin.invitationLink")}
        onClose={() => {
          setInvitation(null);
        }}
      />
    </>
  );
}
