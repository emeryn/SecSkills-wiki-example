import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/** Global search in the top bar; Ctrl+K anywhere and "/" outside text fields focus it. */
export function SearchBox() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [value, setValue] = useState(params.get("q") ?? "");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const ctrlK = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
      const slash = event.key === "/" && !isTyping(event.target);
      if (ctrlK || slash) {
        event.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  return (
    <form
      role="search"
      className="relative mx-auto hidden w-full max-w-md md:block"
      onSubmit={(event) => {
        event.preventDefault();
        const q = value.trim();
        if (q !== "") void navigate(`/search?q=${encodeURIComponent(q)}`);
      }}
    >
      <label htmlFor="global-search" className="sr-only">
        {t("search.label")}
      </label>
      <Search
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-muted"
      />
      <input
        id="global-search"
        ref={input}
        type="search"
        maxLength={200}
        value={value}
        placeholder={t("search.placeholder")}
        onChange={(event) => {
          setValue(event.target.value);
        }}
        className="h-9 w-full rounded-md border border-border bg-surface-muted pr-16 pl-9"
      />
      <kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded-sm border border-border px-1.5 text-xs text-text-muted">
        Ctrl K
      </kbd>
    </form>
  );
}
