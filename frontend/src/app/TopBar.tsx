import { Menu } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import type { ThemePreference } from "../lib/theme";
import { HelpButton } from "./HelpButton";
import { SearchBox } from "./SearchBox";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  onOpenDrawer: () => void;
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
}

export function TopBar({ onOpenDrawer, theme, onThemeChange }: TopBarProps) {
  const { t } = useTranslation();
  return (
    <header className="flex h-(--topbar-height) shrink-0 items-center gap-3 border-b border-border bg-surface px-3">
      <button
        type="button"
        onClick={onOpenDrawer}
        aria-label={t("nav.openMenu")}
        className="flex size-9 items-center justify-center rounded-md hover:bg-surface-muted lg:hidden"
      >
        <Menu aria-hidden className="size-5" />
      </button>
      <Link to="/" className="flex items-center gap-2 font-semibold">
        <img src="/favicon.svg" alt="" className="size-6" />
        <span>{t("app.name")}</span>
      </Link>
      <SearchBox />
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <HelpButton />
        <UserMenu theme={theme} onThemeChange={onThemeChange} />
      </div>
    </header>
  );
}
