import { Archive, FileDown, FilePlus2, Settings, Trash2 } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useOutletContext, useParams } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { Skeleton } from "../../../components/ui/Skeleton";
import { hasPermission, useSession } from "../../../lib/auth";
import { saveBlob } from "../../../lib/download";
import { canRole, useSpace, useTree, type Space, type TreeNode } from "../api";
import { exportArchive } from "../attachments";
import { PageTree } from "../components/PageTree";

export interface SpaceOutletContext {
  space: Space;
  tree: TreeNode[];
}

export function useSpaceContext(): SpaceOutletContext {
  return useOutletContext<SpaceOutletContext>();
}

/** Space shell: page tree on the left, page content on the right. */
export function SpaceLayout() {
  const { t } = useTranslation();
  const { space: key = "", slug } = useParams();
  const session = useSession();
  const space = useSpace(key);
  const readable = space.data?.role != null;
  const tree = useTree(key, readable);
  const exportSpace = useMutation({
    mutationFn: () => exportArchive(key),
    onSuccess: ({ blob, filename }) => {
      saveBlob(blob, filename);
    },
  });

  if (space.isError) return <ErrorState error={space.error} onRetry={() => void space.refetch()} />;
  if (space.data === undefined) return <Skeleton className="h-64 w-full" />;
  const data = space.data;
  const isAdmin = hasPermission(session.data, "spaces:manage");
  const canEdit = canRole(data.role, "editor") && !data.archived;
  const canManage = canRole(data.role, "space_admin") || isAdmin;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="shrink-0 space-y-3 lg:w-64">
        <div>
          <Link to={`/spaces/${key}`} className="text-base font-semibold hover:underline">
            {data.name}
          </Link>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge>{t(`spaces.visibility.${data.visibility}`)}</Badge>
            {data.archived && (
              <Badge tone="danger">
                <Archive aria-hidden className="mr-1 size-3" />
                {t("spaces.archived")}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-1 text-sm">
          {canEdit && (
            <Link
              to={`/spaces/${key}/new`}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-surface-muted"
            >
              <FilePlus2 aria-hidden className="size-4" />
              {t("pages.newPage")}
            </Link>
          )}
          {canEdit && (
            <Link
              to={`/spaces/${key}/trash`}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-surface-muted"
            >
              <Trash2 aria-hidden className="size-4" />
              {t("trash.title")}
            </Link>
          )}
          {readable && (
            <button
              type="button"
              onClick={() => {
                exportSpace.mutate();
              }}
              disabled={exportSpace.isPending}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-surface-muted disabled:opacity-60"
            >
              <FileDown aria-hidden className="size-4" />
              {t("export.space")}
            </button>
          )}
          {canManage && (
            <Link
              to={`/spaces/${key}/settings`}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-surface-muted"
            >
              <Settings aria-hidden className="size-4" />
              {t("spaces.settings")}
            </Link>
          )}
        </div>
        <FormError error={exportSpace.error} />
        {readable &&
          (tree.data === undefined ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <PageTree spaceKey={key} nodes={tree.data} currentSlug={slug} />
          ))}
      </aside>
      <div className="min-w-0 flex-1">
        <Outlet context={{ space: data, tree: tree.data ?? [] } satisfies SpaceOutletContext} />
      </div>
    </div>
  );
}
