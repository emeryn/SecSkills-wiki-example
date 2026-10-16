import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate, NavLink, useParams } from "react-router";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { operationsApi, SECTIONS, type Section } from "../api";
import { BlockedIpsSection } from "../components/BlockedIpsSection";
import { LlmModelsSection, SystemPromptSection } from "../components/LlmSections";
import { SettingsSectionForm } from "../components/SettingsSectionForm";

/** Settings with vertical tabs; the section is part of the URL. */
export function SettingsPage() {
  const { t } = useTranslation();
  const params = useParams();
  const section = SECTIONS.find((candidate) => candidate === params.section);
  const settings = useQuery({
    queryKey: ["admin", "settings", section],
    queryFn: () => operationsApi.settings(section as Section),
    enabled: section !== undefined,
  });
  if (section === undefined) return <Navigate to="/admin/settings/syslog" replace />;

  return (
    <div className="mx-auto max-w-(--content-max-width)">
      <PageHeader
        title={t("settings.title")}
        breadcrumb={[
          { label: t("nav.home"), to: "/" },
          { label: t("settings.title"), to: "/admin/settings/syslog" },
          { label: t(`settings.sections.${section}`) },
        ]}
      />
      <div className="flex flex-col gap-6 md:flex-row">
        <nav
          aria-label={t("settings.title")}
          className="flex shrink-0 flex-wrap gap-1 md:w-48 md:flex-col"
        >
          {SECTIONS.map((value) => (
            <NavLink
              key={value}
              to={`/admin/settings/${value}`}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 hover:bg-surface-muted ${isActive ? "bg-primary/10 font-medium text-primary" : ""}`
              }
            >
              {t(`settings.sections.${value}`)}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          {settings.isError ? (
            <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
          ) : settings.data === undefined ? (
            <div aria-busy className="max-w-2xl space-y-3">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <span className="sr-only">{t("common.loading")}</span>
            </div>
          ) : (
            <SettingsSectionForm
              key={`${section}|${settings.data.updated_at ?? "default"}`}
              data={settings.data}
            />
          )}
          {section === "security" && <BlockedIpsSection />}
          {section === "llm" && settings.data?.values.url != null && (
            <>
              <LlmModelsSection />
              <SystemPromptSection />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
