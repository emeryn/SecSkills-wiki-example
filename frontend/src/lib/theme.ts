import { useCallback, useEffect, useState } from "react";
import { readPreference, writePreference } from "./preferences";

export const THEME_PREFERENCES = ["system", "light", "dark"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

const KEY = "theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function isThemePreference(value: string | null): value is ThemePreference {
  return THEME_PREFERENCES.some((theme) => theme === value);
}

export function readThemePreference(): ThemePreference {
  const stored = readPreference(KEY);
  return isThemePreference(stored) ? stored : "system";
}

/** Sets `data-theme` on the root element; "system" follows the OS setting. */
export function applyTheme(preference: ThemePreference): void {
  const dark =
    preference === "dark" || (preference === "system" && window.matchMedia(DARK_QUERY).matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme(): [ThemePreference, (preference: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference);

  useEffect(() => {
    applyTheme(preference);
    if (preference !== "system") return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => {
      applyTheme("system");
    };
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, [preference]);

  const update = useCallback((next: ThemePreference) => {
    writePreference(KEY, next);
    setPreference(next);
  }, []);

  return [preference, update];
}
