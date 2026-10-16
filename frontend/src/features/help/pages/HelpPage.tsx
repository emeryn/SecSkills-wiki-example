import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, useParams } from "react-router";
import { PageHeader } from "../../../components/ui/PageHeader";
import { SanitizedHtml } from "../../../components/ui/SanitizedHtml";
import { NotFoundPage } from "../../../app/NotFoundPage";
import { useSession } from "../../../lib/auth";
import { renderMarkdown } from "../../../lib/markdown";
import { findTopic, HELP_TOPICS, type Audience } from "../topics";

const ADMIN_PERMISSION = "dashboard:read";

/** User and administrator help, bundled from `docs/help/`. */
export function HelpPage() {
  const { t } = useTranslation();
  const { audience = "user", topic: slug = "getting-started" } = useParams();
  const session = useSession();
  const canAdminister = session.data?.user.permissions.includes(ADMIN_PERMISSION) === true;
  const audiences: Audience[] = canAdminister ? ["user", "admin"] : ["user"];
  const topic = findTopic(audience, slug);
  const html = useMemo(
    // The first heading is the page title (rendered by the page header).
    () =>
      topic !== undefined ? renderMarkdown(topic.source.replace(/^#\s+.+$/m, ""), () => null) : "",
    [topic],
  );
  if (topic === undefined || !audiences.includes(topic.audience)) return <NotFoundPage />;

  return (
    <div className="mx-auto max-w-(--content-max-width)">
      <PageHeader
        title={topic.title}
        breadcrumb={[
          { label: t("nav.home"), to: "/" },
          { label: t("help.title"), to: "/help/user/getting-started" },
          { label: topic.title },
        ]}
      />
      <div className="flex flex-col gap-8 md:flex-row">
        <nav aria-label={t("help.title")} className="shrink-0 space-y-4 md:w-56">
          {audiences.map((group) => (
            <div key={group} className="space-y-1">
              <p className="px-3 text-xs font-semibold tracking-wide text-text-muted uppercase">
                {t(`help.audiences.${group}`)}
              </p>
              <ul className="space-y-0.5">
                {HELP_TOPICS.filter((item) => item.audience === group).map((item) => (
                  <li key={`${item.audience}/${item.slug}`}>
                    <NavLink
                      to={`/help/${item.audience}/${item.slug}`}
                      className={({ isActive }) =>
                        `block rounded-md px-3 py-1.5 hover:bg-surface-muted ${isActive ? "bg-primary/10 font-medium text-primary" : ""}`
                      }
                    >
                      {item.title}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <article className="min-w-0 flex-1">
          <SanitizedHtml html={html} />
        </article>
      </div>
    </div>
  );
}
