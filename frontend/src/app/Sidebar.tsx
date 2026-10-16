import { ChevronsLeft, ChevronsRight, Star } from "lucide-react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";
import { useFavorites } from "../lib/feed";
import { NAVIGATION } from "./navigation";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate: () => void;
  permissions: string[];
}

const MAX_FAVORITES = 10;

export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, permissions }: SidebarProps) {
  const { t } = useTranslation();
  const groups = NAVIGATION.map((group) => ({
    ...group,
    items: group.items.filter(
      (item) => item.permission === undefined || permissions.includes(item.permission),
    ),
  })).filter((group) => group.items.length > 0);
  const favorites = useFavorites();
  const starred = (favorites.data ?? []).slice(0, MAX_FAVORITES);

  return (
    <nav aria-label={t("nav.main")} className="flex h-full flex-col gap-4 p-2">
      {groups.map((group) => (
        <div key={group.labelKey ?? "main"} className="space-y-1">
          {group.labelKey !== undefined && !collapsed && (
            <p className="px-3 pt-2 text-xs font-semibold tracking-wide text-text-muted uppercase">
              {t(group.labelKey)}
            </p>
          )}
          <ul className="space-y-1">
            {group.items.map(({ to, labelKey, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/" || to === "/admin"}
                  onClick={onNavigate}
                  title={collapsed ? t(labelKey) : undefined}
                  className={({ isActive }) =>
                    `flex h-9 items-center gap-3 rounded-md px-3 ${
                      isActive
                        ? "bg-primary/10 font-medium text-primary"
                        : "text-text hover:bg-surface-muted"
                    }`
                  }
                >
                  <Icon aria-hidden className="size-4 shrink-0" />
                  <span className={collapsed ? "sr-only" : undefined}>{t(labelKey)}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {!collapsed && starred.length > 0 && (
        <div className="space-y-1">
          <p className="px-3 pt-2 text-xs font-semibold tracking-wide text-text-muted uppercase">
            {t("nav.favorites")}
          </p>
          <ul className="space-y-0.5">
            {starred.map((favorite) => (
              <li key={favorite.page_id}>
                <NavLink
                  to={`/spaces/${favorite.space_key}/pages/${favorite.slug}`}
                  onClick={onNavigate}
                  title={`${favorite.title} · ${favorite.space_name}`}
                  className={({ isActive }) =>
                    `flex h-8 items-center gap-2 rounded-md px-3 ${isActive ? "bg-primary/10 text-primary" : "text-text hover:bg-surface-muted"}`
                  }
                >
                  <Star aria-hidden className="size-3.5 shrink-0 text-text-muted" />
                  <span className="truncate">{favorite.title}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      )}
      <button
        type="button"
        onClick={onToggleCollapsed}
        aria-label={collapsed ? t("nav.expand") : t("nav.collapse")}
        aria-expanded={!collapsed}
        className="mt-auto hidden h-9 items-center rounded-md px-3 text-text-muted hover:bg-surface-muted lg:flex"
      >
        {collapsed ? (
          <ChevronsRight aria-hidden className="size-4" />
        ) : (
          <ChevronsLeft aria-hidden className="size-4" />
        )}
      </button>
    </nav>
  );
}
