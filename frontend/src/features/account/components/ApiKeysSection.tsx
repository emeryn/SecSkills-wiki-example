import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DataTable } from "../../../components/ui/DataTable";
import { Dialog } from "../../../components/ui/Dialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { useSession } from "../../../lib/auth";
import { formatDateTime } from "../../../lib/format";
import { apiKeysApi, type ApiKey, type ApiKeyScope } from "../api";

const KEYS = ["account", "api-keys"] as const;
const DAYS = ["30", "90", "365"] as const;

function CreateKeyDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (secret: string) => void;
}) {
  const { t } = useTranslation();
  const session = useSession();
  const isAdmin = session.data?.user.role === "admin";
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiKeyScope[]>(["pages:read"]);
  const [days, setDays] = useState<string>("90");
  const [key] = useState(newIdempotencyKey);
  const create = useMutation({
    mutationFn: () => apiKeysApi.create({ name: name.trim(), scopes, days: Number(days) }, key),
    onSuccess: (created) => {
      onCreated(created.secret);
    },
  });
  const options: ApiKeyScope[] = isAdmin
    ? ["pages:read", "pages:write", "admin"]
    : ["pages:read", "pages:write"];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("apiKeys.create")}
      description={t("apiKeys.createHelp")}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <TextField
          label={t("apiKeys.name")}
          required
          maxLength={100}
          value={name}
          placeholder={t("apiKeys.namePlaceholder")}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <fieldset className="space-y-2">
          <legend className="font-medium">{t("apiKeys.scopes")}</legend>
          {options.map((scope) => (
            <label key={scope} className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                checked={scopes.includes(scope)}
                onChange={(event) => {
                  setScopes((current) =>
                    event.target.checked ? [...current, scope] : current.filter((s) => s !== scope),
                  );
                }}
              />
              <span>
                <span className="font-mono">{scope}</span>
                <span className="block text-xs text-text-muted">
                  {t(`apiKeys.scopeHelp.${scope}`)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        <SelectField
          label={t("apiKeys.expiry")}
          hint={scopes.includes("admin") ? t("apiKeys.adminExpiry") : undefined}
          value={days}
          onChange={(event) => {
            setDays(event.target.value);
          }}
          options={DAYS.map((value) => ({
            value,
            label: t("apiKeys.days", { count: Number(value) }),
          }))}
        />
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
            disabled={name.trim() === "" || scopes.length === 0}
          >
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** API keys for MCP clients: the secret is shown once; keys can be revoked at any time. */
export function ApiKeysSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: KEYS, queryFn: apiKeysApi.list });
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const revoke = useMutation({
    mutationFn: (id: string) => apiKeysApi.revoke(id),
    onSuccess: async () => {
      setRevoking(null);
      toast(t("apiKeys.revoked"));
      await queryClient.invalidateQueries({ queryKey: KEYS });
    },
  });

  return (
    <section className="max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-text-muted">{t("apiKeys.help")}</p>
        <Button
          variant="primary"
          icon={<Plus aria-hidden className="size-4" />}
          onClick={() => {
            setCreating(true);
          }}
        >
          {t("apiKeys.create")}
        </Button>
      </div>
      {keys.isError ? (
        <ErrorState error={keys.error} onRetry={() => void keys.refetch()} />
      ) : (
        <DataTable<ApiKey>
          caption={t("account.tabs.api-keys")}
          loading={keys.isPending}
          rows={keys.data}
          rowKey={(row) => row.id}
          empty={
            <EmptyState
              icon={KeyRound}
              title={t("apiKeys.none")}
              description={t("apiKeys.noneHelp")}
            />
          }
          columns={[
            { key: "name", header: t("apiKeys.name"), render: (row) => row.name },
            {
              key: "prefix",
              header: t("apiKeys.prefix"),
              render: (row) => <span className="font-mono">{row.prefix}</span>,
            },
            { key: "scopes", header: t("apiKeys.scopes"), render: (row) => row.scopes.join(", ") },
            {
              key: "status",
              header: t("admin.status"),
              render: (row) => (
                <Badge tone={row.status === "active" ? "success" : "neutral"}>
                  {t(`apiKeys.status.${row.status}`)}
                </Badge>
              ),
            },
            {
              key: "expires",
              header: t("apiKeys.expires"),
              render: (row) => formatDateTime(row.expires_at),
            },
            {
              key: "used",
              header: t("apiKeys.lastUsed"),
              render: (row) => formatDateTime(row.last_used_at),
            },
            {
              key: "actions",
              header: t("pages.actions"),
              render: (row) =>
                row.status === "active" ? (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setRevoking(row);
                    }}
                  >
                    {t("apiKeys.revoke")}
                  </Button>
                ) : null,
            },
          ]}
        />
      )}
      {creating && (
        <CreateKeyDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(created) => {
            setCreating(false);
            setSecret(created);
            void queryClient.invalidateQueries({ queryKey: KEYS });
          }}
        />
      )}
      <Dialog
        open={secret !== null}
        onOpenChange={(open) => {
          if (!open) setSecret(null);
        }}
        title={t("apiKeys.createdTitle")}
        description={t("apiKeys.createdHelp")}
      >
        <div className="space-y-4">
          <input
            readOnly
            aria-label={t("apiKeys.secret")}
            value={secret ?? ""}
            onFocus={(event) => {
              event.target.select();
            }}
            className="h-9 w-full rounded-md border border-border bg-surface-muted px-3 font-mono text-xs"
          />
          <div className="flex justify-end">
            <Button
              variant="primary"
              icon={<Copy aria-hidden className="size-4" />}
              onClick={() => {
                void navigator.clipboard.writeText(secret ?? "").then(() => {
                  toast(t("common.copied"));
                });
              }}
            >
              {t("common.copy")}
            </Button>
          </div>
        </div>
      </Dialog>
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => {
          if (!open) setRevoking(null);
        }}
        title={t("apiKeys.confirmRevoke", { name: revoking?.name ?? "" })}
        description={t("apiKeys.confirmRevokeHelp")}
        confirmLabel={t("apiKeys.revoke")}
        loading={revoke.isPending}
        onConfirm={() => {
          if (revoking !== null) revoke.mutate(revoking.id);
        }}
      />
    </section>
  );
}
