import { X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Outlet } from "react-router";
import { config } from "../lib/config";
import { readPreference, writePreference } from "../lib/preferences";
import { useSession } from "../lib/auth";
import { useTheme } from "../lib/theme";
import { SessionExpiryWarning } from "./SessionExpiryWarning";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const COLLAPSED_KEY = "sidebar.collapsed";

/** Top bar, collapsible sidebar (drawer below 1024 px), content and version footer. */
export function AppShell() {
  const { t } = useTranslation();
  const [theme, setTheme] = useTheme();
  const session = useSession();
  const [collapsed, setCollapsed] = useState(() => readPreference(COLLAPSED_KEY) === "true");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      writePreference(COLLAPSED_KEY, String(!current));
      return !current;
    });
  }, []);
  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [drawerOpen]);

  const sidebarProps = {
    onToggleCollapsed: toggleCollapsed,
    onNavigate: closeDrawer,
    permissions: session.data?.user.permissions ?? [],
  };

  return (
    <div className="flex h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-raised focus:px-3 focus:py-2"
      >
        {t("app.skipToContent")}
      </a>
      <TopBar
        onOpenDrawer={() => {
          setDrawerOpen(true);
        }}
        theme={theme}
        onThemeChange={setTheme}
      />
      <div className="flex min-h-0 flex-1">
        <aside
          className={`hidden shrink-0 border-r border-border bg-surface lg:block ${
            collapsed ? "w-(--sidebar-collapsed-width)" : "w-(--sidebar-width)"
          }`}
        >
          <Sidebar collapsed={collapsed} {...sidebarProps} />
        </aside>

        {drawerOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div aria-hidden className="absolute inset-0 bg-black/40" onClick={closeDrawer} />
            <aside
              role="dialog"
              aria-modal="true"
              aria-label={t("nav.main")}
              className="absolute inset-y-0 left-0 flex w-(--sidebar-width) flex-col bg-surface shadow-raised"
            >
              <button
                type="button"
                onClick={closeDrawer}
                aria-label={t("nav.closeMenu")}
                className="m-2 flex size-9 items-center justify-center self-end rounded-md hover:bg-surface-muted"
                autoFocus
              >
                <X aria-hidden className="size-5" />
              </button>
              <Sidebar collapsed={false} {...sidebarProps} />
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <main id="main" tabIndex={-1} className="flex-1 px-4 py-6 lg:px-8">
            <Outlet />
          </main>
          <footer className="border-t border-border px-4 py-2 text-xs text-text-muted lg:px-8">
            {t("app.version", { version: config.version })}
          </footer>
        </div>
      </div>
      <SessionExpiryWarning />
    </div>
  );
}
