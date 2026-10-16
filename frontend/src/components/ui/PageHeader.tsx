import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export interface Crumb {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  title: string;
  breadcrumb?: Crumb[];
  /** At most one primary action. */
  primaryAction?: ReactNode;
  /** Secondary actions, usually an actions menu. */
  secondaryActions?: ReactNode;
}

export function PageHeader({
  title,
  breadcrumb = [],
  primaryAction,
  secondaryActions,
}: PageHeaderProps) {
  const { t } = useTranslation();
  return (
    <header className="mb-6 space-y-1">
      {breadcrumb.length > 0 && (
        <nav aria-label={t("nav.breadcrumb")}>
          <ol className="flex flex-wrap items-center gap-1 text-text-muted">
            {breadcrumb.map((crumb, index) => (
              <li key={`${crumb.label}-${String(index)}`} className="flex items-center gap-1">
                {index > 0 && <ChevronRight aria-hidden className="size-3" />}
                {crumb.to !== undefined ? (
                  <Link to={crumb.to} className="hover:text-text hover:underline">
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page">{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <div className="flex items-center gap-2">
          {secondaryActions}
          {primaryAction}
        </div>
      </div>
    </header>
  );
}
