import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Pagination } from "../../../components/ui/DataTable";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { formatDateTime } from "../../../lib/format";
import { useUrlState } from "../../../lib/url-state";
import { SEARCH_PAGE_SIZE, searchPages, type SnippetSegment } from "../api";

const DEFAULTS = { q: "", page: "1" };

/** Highlights are rendered as text with <mark>, never by injecting HTML from the server. */
function Snippet({ segments }: { segments: SnippetSegment[] }) {
  return (
    <p className="text-text-muted">
      {segments.map((segment, index) =>
        segment.highlight ? (
          <mark key={index} className="rounded-sm bg-primary/15 px-0.5 text-text">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  );
}

export function SearchPage() {
  const { t } = useTranslation();
  const [state, update] = useUrlState(DEFAULTS);
  const q = state.q.trim();
  const page = Math.max(1, Number.parseInt(state.page, 10) || 1);
  const results = useQuery({
    queryKey: ["search", q, page],
    queryFn: () => searchPages(q, page),
    enabled: q !== "",
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title={q === "" ? t("search.title") : t("search.resultsFor", { q })}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("search.title") }]}
      />
      {q === "" ? (
        <p className="text-text-muted">{t("search.prompt")}</p>
      ) : results.isError ? (
        <ErrorState error={results.error} onRetry={() => void results.refetch()} />
      ) : results.data === undefined ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : results.data.total === 0 ? (
        <EmptyState
          icon={SearchX}
          title={t("search.noResults")}
          description={t("search.noResultsHelp")}
        />
      ) : (
        <>
          <p className="mb-3 text-text-muted" role="status">
            {t("search.count", { count: results.data.total })}
          </p>
          <ol className="space-y-4">
            {results.data.items.map((hit) => (
              <li key={hit.page_id} className="space-y-1">
                <Link
                  to={`/spaces/${hit.space_key}/pages/${hit.slug}`}
                  className="text-base font-medium text-primary hover:underline"
                >
                  {hit.title}
                </Link>
                <p className="text-xs text-text-muted">
                  {hit.space_name} · {formatDateTime(hit.updated_at)}
                </p>
                <Snippet segments={hit.snippet} />
              </li>
            ))}
          </ol>
          {results.data.total > SEARCH_PAGE_SIZE && (
            <Pagination
              page={page}
              pageSize={SEARCH_PAGE_SIZE}
              total={results.data.total}
              onPage={(next) => {
                update({ page: String(next) }, { resetPage: false });
              }}
            />
          )}
        </>
      )}
    </>
  );
}
