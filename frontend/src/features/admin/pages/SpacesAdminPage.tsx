import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Plus } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { DataTable } from "../../../components/ui/DataTable";
import { Dialog } from "../../../components/ui/Dialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { newIdempotencyKey } from "../../../lib/api-client";
import { formatDateTime } from "../../../lib/format";
import { spacesApi, type AdminSpace, type Visibility } from "../../spaces/api";
import { adminApi, type AdminUser } from "../api";

function CreateSpaceDialog({
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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("restricted");
  const [search, setSearch] = useState("");
  const [spaceAdmin, setSpaceAdmin] = useState<AdminUser | null>(null);
  const users = useQuery({
    queryKey: ["admin", "users", { q: search, status: "active" }],
    queryFn: () => adminApi.users({ q: search, status: "active", page_size: 10 }),
    enabled: search.trim().length >= 2 && spaceAdmin === null,
  });
  const create = useMutation({
    mutationFn: () =>
      spacesApi.create(
        { name, description, visibility, space_admin_id: spaceAdmin?.id ?? "" },
        key.current,
      ),
    onSuccess: async (space) => {
      key.current = newIdempotencyKey();
      onOpenChange(false);
      await queryClient.invalidateQueries({ queryKey: ["spaces"] });
      await queryClient.invalidateQueries({ queryKey: ["admin", "spaces"] });
      await navigate(`/spaces/${space.key}/settings`);
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("spaces.create")}
      description={t("spaces.createHelp")}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <TextField
          label={t("spaces.name")}
          required
          maxLength={100}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <TextField
          label={t("admin.description")}
          maxLength={500}
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
        <SelectField
          label={t("spaces.visibilityLabel")}
          value={visibility}
          onChange={(event) => {
            setVisibility(event.target.value as Visibility);
          }}
          options={[
            { value: "restricted", label: t("spaces.visibility.restricted") },
            { value: "internal", label: t("spaces.visibility.internal") },
          ]}
        />
        {spaceAdmin === null ? (
          <div className="space-y-2">
            <TextField
              label={t("spaces.firstAdmin")}
              required
              hint={t("spaces.firstAdminHint")}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
            />
            {users.data !== undefined && (
              <ul className="divide-y divide-border rounded-md border border-border">
                {users.data.items.map((user) => (
                  <li key={user.id}>
                    <button
                      type="button"
                      className="w-full px-3 py-1.5 text-left hover:bg-surface-muted"
                      onClick={() => {
                        setSpaceAdmin(user);
                      }}
                    >
                      {user.username}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p>
            {t("spaces.firstAdmin")}: <span className="font-medium">{spaceAdmin.username}</span>{" "}
            <button
              type="button"
              className="text-primary hover:underline"
              onClick={() => {
                setSpaceAdmin(null);
              }}
            >
              {t("spaces.change")}
            </button>
          </p>
        )}
        <FormError error={create.error} />
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={create.isPending}
            disabled={name.trim() === "" || spaceAdmin === null}
          >
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** All spaces with their settings; administrators manage them without reading their content. */
export function SpacesAdminPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const spaces = useQuery({ queryKey: ["admin", "spaces"], queryFn: spacesApi.adminList });
  const newSpace = (
    <Button
      variant="primary"
      icon={<Plus aria-hidden className="size-4" />}
      onClick={() => {
        setCreating(true);
      }}
    >
      {t("spaces.newSpace")}
    </Button>
  );

  return (
    <>
      <PageHeader
        title={t("spaces.title")}
        breadcrumb={[
          { label: t("nav.home"), to: "/" },
          { label: t("nav.adminGroup") },
          { label: t("spaces.title") },
        ]}
        primaryAction={newSpace}
      />
      <p className="mb-4 text-text-muted">{t("spaces.adminHelp")}</p>
      {spaces.isError ? (
        <ErrorState error={spaces.error} onRetry={() => void spaces.refetch()} />
      ) : (
        <DataTable<AdminSpace>
          caption={t("spaces.title")}
          loading={spaces.isPending}
          rows={spaces.data}
          rowKey={(row) => row.key}
          onRowClick={(row) => void navigate(`/spaces/${row.key}/settings`)}
          empty={
            <EmptyState
              icon={FolderOpen}
              title={t("spaces.none")}
              description={t("spaces.noneAdmin")}
              action={newSpace}
            />
          }
          columns={[
            {
              key: "name",
              header: t("spaces.name"),
              render: (row) => <span className="font-medium">{row.name}</span>,
            },
            {
              key: "key",
              header: t("spaces.key"),
              render: (row) => <code className="font-mono text-xs">{row.key}</code>,
            },
            {
              key: "visibility",
              header: t("spaces.visibilityLabel"),
              render: (row) => <Badge>{t(`spaces.visibility.${row.visibility}`)}</Badge>,
            },
            { key: "members", header: t("admin.members"), render: (row) => row.member_count },
            {
              key: "status",
              header: t("admin.status"),
              render: (row) =>
                row.archived ? (
                  <Badge tone="danger">{t("spaces.archived")}</Badge>
                ) : (
                  <Badge tone="success">{t("status.active")}</Badge>
                ),
            },
            {
              key: "created",
              header: t("admin.created"),
              render: (row) => formatDateTime(row.created_at),
            },
          ]}
        />
      )}
      <CreateSpaceDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
