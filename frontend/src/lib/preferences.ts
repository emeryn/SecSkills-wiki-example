/**
 * Per-browser UI preferences (theme, sidebar state). Never sensitive data.
 * Storage can be unavailable (private mode, blocked site data): every access falls back silently.
 */
const PREFIX = "wiki.";

export function readPreference(key: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function writePreference(key: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + key, value);
  } catch {
    // Preference is kept for this page view only.
  }
}
