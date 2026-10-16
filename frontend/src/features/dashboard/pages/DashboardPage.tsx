import { useQuery } from "@tanstack/react-query";
import { FolderOpen, History, Star, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useFavorites, useRecentChanges } from "../../../lib/feed";
import { formatDateTime } from "../../../lib/format";
import { spaceKeys, spacesApi } from "../../spaces/api";

interface SectionProps<T> {
  id: string;
  title: string;
  icon: LucideIcon;
  emptyText: string;
  query: { data: T[] | undefined; isError: boolean; error: unknown; refetch: () => unknown };
  render: (item: T) => ReactNode;
  itemKey: (item: T) => string;
}

function Section<T>({ id, title, icon, emptyText, query, render, itemKey }: SectionProps<T>) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="text-base font-semibold">
        {title}
      </h2>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data === undefined ? (
        <Skeleton className="h-32 w-full" />
      ) : query.data.length === 0 ? (
        <EmptyState icon={icon} title={title} description={emptyText} />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {query.data.map((item) => (
            <li key={itemKey(item)} className="px-3 py-2">
              {render(item)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();
  const favorites = useFavorites();
  const recent = useRecentChanges(10);
  const spaces = useQuery({ queryKey: spaceKeys.all, queryFn: spacesApi.list });

  return (
    <>
      <PageHeader title={t("dashboard.title")} />
      <div className="grid gap-6 xl:grid-cols-3">
        <Section
          id="favorites"
          title={t("dashboard.favorites")}
          icon={Star}
          emptyText={t("dashboard.favoritesEmpty")}
          query={favorites}
          itemKey={(f) => f.page_id}
          render={(f) => (
            <Link to={`/spaces/${f.space_key}/pages/${f.slug}`} className="block hover:underline">
              <span className="font-medium">{f.title}</span>
              <span className="text-text-muted"> · {f.space_name}</span>
            </Link>
          )}
        />
        <Section
          id="recent"
          title={t("dashboard.recentChanges")}
          icon={History}
          emptyText={t("dashboard.recentChangesEmpty")}
          query={recent}
          itemKey={(c) => `${c.page_id}-${String(c.revision_number)}`}
          render={(c) => (
            <Link to={`/spaces/${c.space_key}/pages/${c.slug}`} className="block hover:underline">
              <span className="font-medium">{c.title}</span>
              <span className="block text-xs text-text-muted">
                {c.space_name} · {c.author ?? "—"} · {formatDateTime(c.created_at)}
              </span>
            </Link>
          )}
        />
        <Section
          id="spaces"
          title={t("dashboard.mySpaces")}
          icon={FolderOpen}
          emptyText={t("dashboard.mySpacesEmpty")}
          query={spaces}
          itemKey={(s) => s.key}
          render={(s) => (
            <Link to={`/spaces/${s.key}`} className="font-medium hover:underline">
              {s.name}
            </Link>
          )}
        />
      </div>
    </>
  );
}
