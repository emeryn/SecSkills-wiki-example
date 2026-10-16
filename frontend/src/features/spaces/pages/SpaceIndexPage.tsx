import { ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router";
import { EmptyState } from "../../../components/ui/EmptyState";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useSpaceContext } from "./SpaceLayout";

/** `/spaces/:space` shows the home page; administrators who are not members see settings only. */
export function SpaceIndexPage() {
  const { t } = useTranslation();
  const { space, tree } = useSpaceContext();
  if (space.role === null) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title={t("spaces.notMemberTitle")}
        description={t("spaces.notMemberHelp")}
        action={
          <Link to={`/spaces/${space.key}/settings`} className="text-primary hover:underline">
            {t("spaces.settings")}
          </Link>
        }
      />
    );
  }
  const home = tree.find((node) => node.id === space.home_page_id) ?? tree[0];
  if (home === undefined) return <Skeleton className="h-64 w-full" />;
  return <Navigate to={`/spaces/${space.key}/pages/${home.slug}`} replace />;
}
