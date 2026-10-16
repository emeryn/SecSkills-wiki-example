import { useQuery } from "@tanstack/react-query";
import { FolderOpen, Lock, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Badge } from "../../../components/ui/Badge";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { hasPermission, useSession } from "../../../lib/auth";
import { spaceKeys, spacesApi } from "../api";

export function SpacesPage() {
  const { t } = useTranslation();
  const session = useSession();
  const spaces = useQuery({ queryKey: spaceKeys.all, queryFn: spacesApi.list });
  const isAdmin = hasPermission(session.data, "spaces:manage");

  return (
    <>
      <PageHeader
        title={t("spaces.title")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("spaces.title") }]}
        primaryAction={
          isAdmin ? (
            <Link
              to="/admin/spaces"
              className="inline-flex h-9 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-surface-muted"
            >
              {t("spaces.manage")}
            </Link>
          ) : undefined
        }
      />
      {spaces.isError ? (
        <ErrorState error={spaces.error} onRetry={() => void spaces.refetch()} />
      ) : spaces.data === undefined ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : spaces.data.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title={t("spaces.none")}
          description={isAdmin ? t("spaces.noneAdmin") : t("spaces.noneHelp")}
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {spaces.data.map((space) => (
            <li key={space.key}>
              <Link
                to={`/spaces/${space.key}`}
                className="block h-full space-y-2 rounded-lg border border-border p-4 hover:border-primary/60 hover:bg-surface-muted"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{space.name}</span>
                  {space.visibility === "restricted" ? (
                    <Lock
                      aria-label={t("spaces.visibility.restricted")}
                      className="size-4 text-text-muted"
                    />
                  ) : (
                    <Users
                      aria-label={t("spaces.visibility.internal")}
                      className="size-4 text-text-muted"
                    />
                  )}
                </div>
                {space.description !== "" && (
                  <p className="line-clamp-2 text-text-muted">{space.description}</p>
                )}
                {space.role !== null && (
                  <Badge tone="primary">{t(`spaces.roles.${space.role}`)}</Badge>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
