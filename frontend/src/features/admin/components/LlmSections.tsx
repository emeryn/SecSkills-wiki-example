import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DataTable } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { formatBytes, formatDateTime } from "../../../lib/format";
import { operationsApi, type LlmModel, type PromptState } from "../api";

/** Models the inference server offers; approved ones are pinned by digest. */
export function LlmModelsSection() {
  const { t } = useTranslation();
  const models = useQuery({
    queryKey: ["admin", "llm", "models"],
    queryFn: operationsApi.llmModels,
    retry: false,
  });
  return (
    <section className="mt-10 max-w-3xl space-y-3">
      <h2 className="text-lg font-semibold">{t("llm.models")}</h2>
      {models.isError ? (
        <ErrorState error={models.error} onRetry={() => void models.refetch()} />
      ) : (
        <DataTable<LlmModel>
          caption={t("llm.models")}
          loading={models.isPending}
          rows={models.data}
          rowKey={(row) => row.name}
          empty={
            <EmptyState icon={Cpu} title={t("llm.noModels")} description={t("llm.noModelsHelp")} />
          }
          columns={[
            {
              key: "name",
              header: t("llm.model"),
              render: (row) => <span className="font-mono">{row.name}</span>,
            },
            { key: "format", header: t("llm.format"), render: (row) => row.format },
            { key: "size", header: t("llm.size"), render: (row) => formatBytes(row.size_bytes) },
            {
              key: "digest",
              header: t("llm.digest"),
              render: (row) => <span className="font-mono text-xs">{row.digest.slice(0, 19)}</span>,
            },
            {
              key: "approved",
              header: t("llm.approval"),
              render: (row) =>
                row.approved ? <Badge tone="success">{t("llm.approved")}</Badge> : "—",
            },
          ]}
        />
      )}
    </section>
  );
}

/** System prompt: edit (a new version each time), history, reset to the factory text. */
export function SystemPromptSection() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const id = useId();
  const prompt = useQuery({
    queryKey: ["admin", "llm", "prompt"],
    queryFn: operationsApi.llmPrompt,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const onSaved = (state: PromptState) => {
    queryClient.setQueryData(["admin", "llm", "prompt"], state);
    setDraft(null);
    setKey(newIdempotencyKey());
  };
  const save = useMutation({
    mutationFn: (content: string) => operationsApi.saveLlmPrompt(content, key),
    onSuccess: (state) => {
      onSaved(state);
      toast(t("common.saved"));
    },
  });
  const reset = useMutation({
    mutationFn: operationsApi.resetLlmPrompt,
    onSuccess: (state) => {
      setConfirmReset(false);
      onSaved(state);
      toast(t("settings.resetDone"));
    },
  });
  if (prompt.isError)
    return <ErrorState error={prompt.error} onRetry={() => void prompt.refetch()} />;
  if (prompt.data === undefined) return null;
  const value = draft ?? prompt.data.current;

  return (
    <section className="mt-10 max-w-3xl space-y-3">
      <h2 className="text-lg font-semibold">{t("llm.systemPrompt")}</h2>
      <p className="text-text-muted">{t("llm.systemPromptHelp")}</p>
      <label htmlFor={id} className="sr-only">
        {t("llm.systemPrompt")}
      </label>
      <textarea
        id={id}
        rows={10}
        maxLength={20000}
        value={value}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        className="w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs"
      />
      <FormError error={save.error ?? reset.error} />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          loading={save.isPending}
          disabled={draft === null || draft.trim() === ""}
          onClick={() => {
            save.mutate(value);
          }}
        >
          {t("common.save")}
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setConfirmReset(true);
          }}
        >
          {t("settings.reset")}
        </Button>
      </div>
      {prompt.data.versions.length > 0 && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-text-muted uppercase">
            {t("llm.versions")}
          </p>
          <ul className="mt-1 space-y-1 text-text-muted">
            {prompt.data.versions.map((version) => (
              <li key={version.id}>
                {t("llm.versionLine", {
                  date: formatDateTime(version.created_at),
                  user: version.created_by ?? "—",
                })}
                {version.is_default && (
                  <span className="ml-2">
                    <Badge>{t("llm.factory")}</Badge>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title={t("llm.confirmReset")}
        description={t("llm.confirmResetHelp")}
        confirmLabel={t("settings.reset")}
        loading={reset.isPending}
        onConfirm={() => {
          reset.mutate();
        }}
      />
    </section>
  );
}
