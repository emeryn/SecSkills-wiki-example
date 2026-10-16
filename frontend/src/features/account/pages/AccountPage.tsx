import * as Tabs from "@radix-ui/react-tabs";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";
import { PageHeader } from "../../../components/ui/PageHeader";
import { useToast } from "../../../components/ui/Toast";
import { useSession } from "../../../lib/auth";
import { ApiKeysSection } from "../components/ApiKeysSection";
import { PasswordForm } from "../components/PasswordForm";
import { SecuritySection } from "../components/SecuritySection";
import { SessionsSection } from "../components/SessionsSection";

const TABS = ["profile", "password", "security", "sessions", "api-keys"] as const;
type Tab = (typeof TABS)[number];

export function AccountPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const session = useSession();
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const user = session.data?.user;
  // Passwords and second factors of SSO accounts are managed by the identity provider.
  const tabs =
    user?.auth_source === "local"
      ? TABS
      : TABS.filter((name) => name !== "password" && name !== "security");
  const tab: Tab = tabs.find((candidate) => candidate === requested) ?? "profile";

  return (
    <div className="mx-auto max-w-(--content-max-width)">
      <PageHeader
        title={t("account.title")}
        breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("account.title") }]}
      />
      <Tabs.Root
        value={tab}
        onValueChange={(value) => {
          setParams({ tab: value }, { replace: true });
        }}
        orientation="vertical"
        className="flex flex-col gap-6 md:flex-row"
      >
        <Tabs.List
          aria-label={t("account.title")}
          className="flex shrink-0 gap-1 md:w-48 md:flex-col"
        >
          {tabs.map((value) => (
            <Tabs.Trigger
              key={value}
              value={value}
              className="rounded-md px-3 py-2 text-left hover:bg-surface-muted data-[state=active]:bg-primary/10 data-[state=active]:font-medium data-[state=active]:text-primary"
            >
              {t(`account.tabs.${value}`)}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <div className="min-w-0 flex-1">
          <Tabs.Content value="profile">
            <dl className="grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-2">
              <dt className="text-text-muted">{t("auth.username")}</dt>
              <dd>{user?.username}</dd>
              <dt className="text-text-muted">{t("account.displayName")}</dt>
              <dd>{user?.display_name ?? "—"}</dd>
              <dt className="text-text-muted">{t("auth.email")}</dt>
              <dd>{user?.email ?? "—"}</dd>
              <dt className="text-text-muted">{t("account.role")}</dt>
              <dd>{user !== undefined ? t(`roles.${user.role}`) : ""}</dd>
            </dl>
            <p className="mt-4 text-text-muted">{t("account.profileManaged")}</p>
          </Tabs.Content>
          <Tabs.Content value="password">
            <PasswordForm
              onDone={() => {
                toast(t("account.passwordChanged"));
              }}
            />
          </Tabs.Content>
          <Tabs.Content value="security">
            <SecuritySection />
          </Tabs.Content>
          <Tabs.Content value="sessions">
            <SessionsSection />
          </Tabs.Content>
          <Tabs.Content value="api-keys">
            <ApiKeysSection />
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}
