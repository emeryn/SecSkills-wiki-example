import { FileQuestion } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { EmptyState } from "../components/ui/EmptyState";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl py-12">
      <h1 className="sr-only">{t("errors.notFoundTitle")}</h1>
      <EmptyState
        icon={FileQuestion}
        title={t("errors.notFoundTitle")}
        description={t("errors.notFoundMessage")}
        action={
          <Link to="/" className="text-primary hover:underline">
            {t("errors.backHome")}
          </Link>
        }
      />
    </div>
  );
}
