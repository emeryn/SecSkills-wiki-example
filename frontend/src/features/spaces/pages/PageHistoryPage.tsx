import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DataTable, Pagination } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { canRole } from "../api";
import { DiffView } from "../components/DiffView";
import { pageKeys, pagesApi, type RevisionSummary } from "../page-api";
import { useSpaceContext } from "./SpaceLayout";

const PAGE_SIZE = 25;

/** Revision list; pick two revisions to compare (kept in the URL), restore an old one. */
export function PageHistoryPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { space } = useSpaceContext();
  const { slug = "" } = useParams();
  const [state, update] = useUrlState({ from: "", to: "", page: "1" });
  const [restoring, setRestoring] = useState<RevisionSummary | null>(null);
  // Selection answers the click immediately; the URL mirrors it for back button and sharing.
  const [selected, setSelected] = useState({ from: state.from, to: state.to });
  const pageNumber = Math.max(1, Number.parseInt(state.page, 10) || 1);
  const page = useQuery({
    queryKey: pageKeys.bySlug(space.key, slug),
    queryFn: () => pagesApi.bySlug(space.key, slug),
  });
  const pageId = page.data?.id ?? "";
  const revisions = useQuery({
    queryKey: pageKeys.revisions(space.key, pageId, pageNumber),
    queryFn: () => pagesApi.revisions(space.key, pageId, pageNumber),
    enabled: pageId !== "",
    placeholderData: keepPreviousData,
  });
  const diff = useQuery({
    queryKey: ["diff", space.key, pageId, selected.from, selected.to],
    queryFn: () => pagesApi.diff(space.key, pageId, selected.to, selected.from),
    enabled:
      pageId !== "" && selected.from !== "" && selected.to !== "" && selected.from !== selected.to,
  });
  const restore = useMutation({
    mutationFn: (revision: RevisionSummary) =>
      pagesApi.restoreRevision(space.key, pageId, revision.id),
    onSuccess: async (restored) => {
      setRestoring(null);
      queryClient.setQueryData(pageKeys.bySlug(space.key, restored.slug), restored);
      await queryClient.invalidateQueries({ queryKey: ["pages", space.key, pageId] });
      toast(t("history.restored"));
      await navigate(`/spaces/${space.key}/pages/${restored.slug}`);
    },
  });

  if (page.isError) return <ErrorState error={page.error} onRetry={() => void page.refetch()} />;
  if (page.data === undefined) return <Skeleton className="h-64 w-full" />;
  const data = page.data;
  const canEdit = canRole(space.role, "editor") && !space.archived;
  const radio = (name: "from" | "to", revision: RevisionSummary) => (
    <input
      type="radio"
      name={name}
      aria-label={t(`history.${name}`, { number: revision.number })}
      checked={selected[name] === revision.id}
      onChange={() => {
        setSelected((current) => ({ ...current, [name]: revision.id }));
        update({ [name]: revision.id }, { resetPage: false });
      }}
    />
  );

  return (
    <>
      <PageHeader
        title={t("history.titleFor", { title: data.title })}
        breadcrumb={[
          { label: space.name, to: `/spaces/${space.key}` },
          { label: data.title, to: `/spaces/${space.key}/pages/${data.slug}` },
          { label: t("history.title") },
        ]}
      />
      {revisions.isError ? (
        <ErrorState error={revisions.error} onRetry={() => void revisions.refetch()} />
      ) : (
        <>
          <DataTable<RevisionSummary>
            caption={t("history.title")}
            loading={revisions.isPending}
            rows={revisions.data?.items}
            rowKey={(row) => row.id}
            empty={
              <EmptyState
                icon={History}
                title={t("history.title")}
                description={t("history.empty")}
              />
            }
            columns={[
              { key: "from", header: t("history.fromColumn"), render: (row) => radio("from", row) },
              { key: "to", header: t("history.toColumn"), render: (row) => radio("to", row) },
              { key: "number", header: "#", render: (row) => row.number },
              { key: "message", header: t("editor.message"), render: (row) => row.message || "—" },
              { key: "author", header: t("history.author"), render: (row) => row.author ?? "—" },
              {
                key: "date",
                header: t("history.date"),
                render: (row) => formatDateTime(row.created_at),
              },
              {
                key: "restore",
                header: "",
                render: (row) =>
                  canEdit && row.id !== data.revision_id ? (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setRestoring(row);
                      }}
                    >
                      {t("history.restore")}
                    </Button>
                  ) : null,
              },
            ]}
          />
          {revisions.data !== undefined && revisions.data.total > PAGE_SIZE && (
            <Pagination
              page={pageNumber}
              pageSize={PAGE_SIZE}
              total={revisions.data.total}
              onPage={(next) => {
                update({ page: String(next) }, { resetPage: false });
              }}
            />
          )}
        </>
      )}
      <section className="mt-6 space-y-2">
        <h2 className="text-base font-semibold">{t("history.diff")}</h2>
        {selected.from === "" || selected.to === "" ? (
          <p className="text-text-muted">{t("history.pickTwo")}</p>
        ) : diff.isError ? (
          <ErrorState error={diff.error} onRetry={() => void diff.refetch()} />
        ) : diff.data === undefined ? (
          <Skeleton className="h-32 w-full" />
        ) : (
          <DiffView lines={diff.data.lines} />
        )}
      </section>
      <ConfirmDialog
        open={restoring !== null}
        onOpenChange={(open) => {
          if (!open) setRestoring(null);
        }}
        title={t("history.confirmRestore", { number: restoring?.number ?? 0 })}
        description={t("history.confirmRestoreHelp")}
        confirmLabel={t("history.restore")}
        destructive={false}
        loading={restore.isPending}
        onConfirm={() => {
          if (restoring !== null) restore.mutate(restoring);
        }}
      />
      <FormError error={restore.error} />
    </>
  );
}
