import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleUser, LogOut, UserCog } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";
import { setCsrfToken } from "../lib/api-client";
import { SESSION_KEY, useSession } from "../lib/auth";
import { THEME_PREFERENCES, type ThemePreference } from "../lib/theme";
import { authApi } from "../features/auth/api";

const THEME_LABELS: Record<ThemePreference, string> = {
  system: "userMenu.themeSystem",
  light: "userMenu.themeLight",
  dark: "userMenu.themeDark",
};

const ITEM =
  "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 outline-none data-highlighted:bg-surface-muted";

interface UserMenuProps {
  theme: ThemePreference;
  onThemeChange: (theme: ThemePreference) => void;
}

export function UserMenu({ theme, onThemeChange }: UserMenuProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useSession().data?.user;

  const signOut = async () => {
    try {
      await authApi.logout();
    } finally {
      setCsrfToken(null);
      queryClient.clear();
      queryClient.setQueryData(SESSION_KEY, null);
      await navigate("/login");
    }
  };

  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={t("userMenu.label")}
        className="flex h-9 items-center gap-2 rounded-md px-2 hover:bg-surface-muted"
      >
        <CircleUser aria-hidden className="size-5" />
        <span className="hidden sm:inline">{user?.display_name ?? user?.username}</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="z-50 min-w-52 rounded-md border border-border bg-surface-raised p-1 text-text shadow-raised"
        >
          <DropdownMenu.Item className={ITEM} onSelect={() => void navigate("/account")}>
            <UserCog aria-hidden className="size-4" />
            {t("userMenu.account")}
          </DropdownMenu.Item>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Label className="px-2 py-1.5 text-xs font-semibold text-text-muted">
            {t("userMenu.theme")}
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup
            value={theme}
            onValueChange={(value) => {
              const next = THEME_PREFERENCES.find((candidate) => candidate === value);
              if (next !== undefined) onThemeChange(next);
            }}
          >
            {THEME_PREFERENCES.map((option) => (
              <DropdownMenu.RadioItem
                key={option}
                value={option}
                className={`${ITEM} justify-between`}
              >
                {t(THEME_LABELS[option])}
                <DropdownMenu.ItemIndicator>
                  <Check aria-hidden className="size-4" />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item className={ITEM} onSelect={() => void signOut()}>
            <LogOut aria-hidden className="size-4" />
            {t("userMenu.signOut")}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
