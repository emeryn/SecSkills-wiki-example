import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, FolderInput, History, MoreHorizontal, Pencil, Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { feedApi, feedKeys } from "../../../lib/feed";
import { saveBlob } from "../../../lib/download";
import { formatDateTime } from "../../../lib/format";
import { canRole, spaceKeys } from "../api";
import { exportArchive } from "../attachments";
import { AttachmentsSection } from "../components/AttachmentsSection";
import { MarkdownView } from "../components/MarkdownView";
import { MoveDialog } from "../components/MoveDialog";
import { pageKeys, pagesApi, type PageData } from "../page-api";
import { useSpaceContext } from "./SpaceLayout";

const MENU_ITEM =
  "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 outline-none data-highlighted:bg-surface-muted";

export function PageViewPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { space, tree } = useSpaceContext();
  const { slug = "" } = useParams();
  const page = useQuery({
    queryKey: pageKeys.bySlug(space.key, slug),
    queryFn: () => pagesApi.bySlug(space.key, slug),
  });
  const [moving, setMoving] = useState<PageData | null>(null);
  const [deleting, setDeleting] = useState(false);

  const favorite = useMutation({
    mutationFn: (data: PageData) =>
      data.favorite ? feedApi.removeFavorite(data.id) : feedApi.addFavorite(data.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: pageKeys.bySlug(space.key, slug) });
      await queryClient.invalidateQueries({ queryKey: feedKeys.favorites });
    },
  });
  const exportPage = useMutation({
    mutationFn: (data: PageData) => exportArchive(space.key, data.id),
    onSuccess: ({ blob, filename }) => {
      saveBlob(blob, filename);
    },
  });
  const remove = useMutation({
    mutationFn: (data: PageData) => pagesApi.remove(space.key, data.id),
    onSuccess: async () => {
      setDeleting(false);
      await queryClient.invalidateQueries({ queryKey: spaceKeys.tree(space.key) });
      toast(t("pages.movedToTrash"));
      await navigate(`/spaces/${space.key}`);
    },
  });

  if (page.isError) return <ErrorState error={page.error} onRetry={() => void page.refetch()} />;
  if (page.data === undefined) return <Skeleton className="h-96 w-full" />;
  const data = page.data;
  const canEdit = canRole(space.role, "editor") && !space.archived;

  return (
    <article>
      <PageHeader
        title={data.title}
        breadcrumb={[
          { label: t("spaces.title"), to: "/spaces" },
          { label: space.name, to: `/spaces/${space.key}` },
          ...data.ancestors.map((a) => ({
            label: a.title,
            to: `/spaces/${space.key}/pages/${a.slug}`,
          })),
          { label: data.title },
        ]}
        primaryAction={
          canEdit ? (
            <Link
              to={`/spaces/${space.key}/pages/${data.slug}/edit`}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover"
            >
              <Pencil aria-hidden className="size-4" />
              {t("pages.edit")}
            </Link>
          ) : undefined
        }
        secondaryActions={
          <>
            <Button
              variant="ghost"
              aria-pressed={data.favorite}
              aria-label={data.favorite ? t("pages.unstar") : t("pages.star")}
              icon={
                <Star
                  aria-hidden
                  className={`size-4 ${data.favorite ? "fill-current text-primary" : ""}`}
                />
              }
              onClick={() => {
                favorite.mutate(data);
              }}
            />
            <DropdownMenu.Root modal={false}>
              <DropdownMenu.Trigger
                aria-label={t("pages.actions")}
                className="flex size-9 items-center justify-center rounded-md hover:bg-surface-muted"
              >
                <MoreHorizontal aria-hidden className="size-4" />
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content
                  align="end"
                  sideOffset={4}
                  className="z-50 min-w-44 rounded-md border border-border bg-surface-raised p-1 text-text shadow-raised"
                >
                  <DropdownMenu.Item
                    className={MENU_ITEM}
                    onSelect={() =>
                      void navigate(`/spaces/${space.key}/pages/${data.slug}/history`)
                    }
                  >
                    <History aria-hidden className="size-4" />
                    {t("history.title")}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item
                    className={MENU_ITEM}
                    onSelect={() => {
                      exportPage.mutate(data);
                    }}
                  >
                    <FileDown aria-hidden className="size-4" />
                    {t("export.page")}
                  </DropdownMenu.Item>
                  {canEdit && (
                    <DropdownMenu.Item
                      className={MENU_ITEM}
                      onSelect={() => {
                        setMoving(data);
                      }}
                    >
                      <FolderInput aria-hidden className="size-4" />
                      {t("pages.move")}
                    </DropdownMenu.Item>
                  )}
                  {canEdit && !data.is_home && (
                    <DropdownMenu.Item
                      className={`${MENU_ITEM} text-danger`}
                      onSelect={() => {
                        setDeleting(true);
                      }}
                    >
                      <Trash2 aria-hidden className="size-4" />
                      {t("common.delete")}
                    </DropdownMenu.Item>
                  )}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
          </>
        }
      />
      <FormError error={favorite.error ?? exportPage.error} />
      <MarkdownView source={data.body} spaceKey={space.key} tree={tree} />
      <AttachmentsSection spaceKey={space.key} pageId={data.id} canEdit={canEdit} />
      <p className="mt-8 border-t border-border pt-3 text-xs text-text-muted">
        {t("pages.revisionInfo", {
          number: data.revision_number,
          author: data.updated_by ?? "—",
          date: formatDateTime(data.updated_at),
        })}
      </p>
      <MoveDialog
        page={moving}
        tree={tree}
        onClose={(moved) => {
          setMoving(null);
          if (moved !== null) {
            queryClient.setQueryData(pageKeys.bySlug(space.key, moved.slug), moved);
            toast(t("pages.moved"));
          }
        }}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t("pages.confirmDelete", { title: data.title })}
        description={t("pages.confirmDeleteHelp")}
        confirmLabel={t("pages.moveToTrash")}
        loading={remove.isPending}
        onConfirm={() => {
          remove.mutate(data);
        }}
      />
      <FormError error={remove.error} />
    </article>
  );
}
