import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "./Skeleton";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading: boolean;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
  onRowClick?: (row: T) => void;
  empty: ReactNode;
  caption: string;
}

/** Server-driven table: sorting and paging state live in the URL of the calling page. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  sort,
  order,
  onSort,
  onRowClick,
  empty,
  caption,
}: DataTableProps<T>) {
  const { t } = useTranslation();
  if (!loading && rows?.length === 0) return <>{empty}</>;
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-muted text-xs text-text-muted uppercase">
          <tr>
            {columns.map((column) => {
              const active = sort === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className="px-3 py-2 font-semibold"
                  aria-sort={active ? (order === "desc" ? "descending" : "ascending") : undefined}
                >
                  {column.sortable === true && onSort !== undefined ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 uppercase hover:text-text"
                      onClick={() => {
                        onSort(column.key);
                      }}
                    >
                      {column.header}
                      {active &&
                        (order === "desc" ? (
                          <ArrowDown aria-hidden className="size-3" />
                        ) : (
                          <ArrowUp aria-hidden className="size-3" />
                        ))}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody aria-busy={loading || undefined}>
          {loading || rows === undefined
            ? [0, 1, 2].map((i) => (
                <tr key={i} className="border-t border-border">
                  <td colSpan={columns.length} className="px-3 py-3">
                    <Skeleton />
                    <span className="sr-only">{t("common.loading")}</span>
                  </td>
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  className={`border-t border-border ${onRowClick !== undefined ? "cursor-pointer hover:bg-surface-muted" : ""}`}
                  onClick={
                    onRowClick !== undefined
                      ? () => {
                          onRowClick(row);
                        }
                      : undefined
                  }
                >
                  {columns.map((column) => (
                    <td key={column.key} className="px-3 py-2">
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label={t("common.pagination")} className="mt-3 flex items-center justify-between">
      <p className="text-text-muted">{t("common.pageOf", { page, pages, total })}</p>
      <div className="flex gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => {
            onPage(page - 1);
          }}
          aria-label={t("common.previousPage")}
          className="flex size-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
        >
          <ChevronLeft aria-hidden className="size-4" />
        </button>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => {
            onPage(page + 1);
          }}
          aria-label={t("common.nextPage")}
          className="flex size-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
        >
          <ChevronRight aria-hidden className="size-4" />
        </button>
      </div>
    </nav>
  );
}
