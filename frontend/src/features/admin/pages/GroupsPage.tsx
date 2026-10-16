import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search, UsersRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Button } from "../../../components/ui/Button";
import { DataTable, Pagination } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { adminApi, type Group } from "../api";
import { CreateGroupDialog } from "../components/GroupFormDialog";

const DEFAULTS = { q: "", sort: "name", order: "asc", page: "1" };
const ALLOWED = { sort: ["name", "created_at"], order: ["asc", "desc"] } as const;
const PAGE_SIZE = 25;

export function GroupsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [state, update] = useUrlState(DEFAULTS, ALLOWED);
  const [search, setSearch] = useState(state.q);
  const [creating, setCreating] = useState(false);
  const page = Math.max(1, Number.parseInt(state.page, 10) || 1);
  const groups = useQuery({
    queryKey: ["admin", "groups", state],
    queryFn: () => adminApi.groups({ ...state, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const newGroup = (
    <Button
      variant="primary"
      icon={<Plus aria-hidden className="size-4" />}
      onClick={() => {
        setCreating(true);
      }}
    >
      {t("admin.newGroup")}
    </Button>
  );

  return (
    <>
      <PageHeader
        title={t("admin.groups")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("admin.groups") }]}
        primaryAction={newGroup}
      />
      <form
        role="search"
        className="mb-4 flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          update({ q: search.trim() });
        }}
      >
        <label htmlFor="group-search" className="sr-only">
          {t("admin.searchGroups")}
        </label>
        <input
          id="group-search"
          type="search"
          value={search}
          placeholder={t("admin.searchGroups")}
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
      {groups.isError ? (
        <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
      ) : (
        <>
          <DataTable<Group>
            caption={t("admin.groups")}
            loading={groups.isPending}
            rows={groups.data?.items}
            rowKey={(row) => row.id}
            sort={state.sort}
            order={state.order === "desc" ? "desc" : "asc"}
            onSort={(key) => {
              update({
                sort: key,
                order: state.sort === key && state.order === "asc" ? "desc" : "asc",
              });
            }}
            onRowClick={(row) => void navigate(`/admin/groups/${row.id}`)}
            empty={
              <EmptyState
                icon={UsersRound}
                title={t("admin.noGroups")}
                description={t("admin.noGroupsHelp")}
                action={newGroup}
              />
            }
            columns={[
              {
                key: "name",
                header: t("admin.groupName"),
                sortable: true,
                render: (row) => <span className="font-medium">{row.name}</span>,
              },
              {
                key: "description",
                header: t("admin.description"),
                render: (row) => row.description || "—",
              },
              { key: "members", header: t("admin.members"), render: (row) => row.member_count },
              {
                key: "created_at",
                header: t("admin.created"),
                sortable: true,
                render: (row) => formatDateTime(row.created_at),
              },
            ]}
          />
          {groups.data !== undefined && groups.data.total > 0 && (
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={groups.data.total}
              onPage={(next) => {
                update({ page: String(next) }, { resetPage: false });
              }}
            />
          )}
        </>
      )}
      <CreateGroupDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
