import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router";
import { helpPathFor } from "../features/help/topics";
import { useSession } from "../lib/auth";

/** `(?)`: help for the page being shown. */
export function HelpButton() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const session = useSession();
  const canAdminister = session.data?.user.permissions.includes("dashboard:read") === true;
  return (
    <Link
      to={helpPathFor(pathname, canAdminister)}
      aria-label={t("help.open")}
      title={t("help.open")}
      className="flex size-9 items-center justify-center rounded-md hover:bg-surface-muted"
    >
      <CircleHelp aria-hidden className="size-5" />
    </Link>
  );
}
