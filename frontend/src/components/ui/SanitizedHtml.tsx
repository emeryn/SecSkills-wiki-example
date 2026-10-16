import { useLayoutEffect, useRef } from "react";
import { useNavigate } from "react-router";
import type { SafeHtml } from "../../lib/markdown";

/** Renders the output of `renderMarkdown`; same-origin links navigate inside the app. */
export function SanitizedHtml({ html }: { html: SafeHtml }) {
  const navigate = useNavigate();
  const container = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (container.current === null) return;
    // The only HTML sink of the app: content went through markdown-it (html disabled) and
    // DOMPurify, and is a TrustedHTML value under the CSP.
    // eslint-disable-next-line no-restricted-syntax
    container.current.innerHTML = html as string;
  }, [html]);

  return (
    <div
      ref={container}
      className="wiki-content"
      onClick={(event) => {
        const anchor = (event.target as HTMLElement).closest("a");
        const href = anchor?.getAttribute("href");
        if (
          href?.startsWith("/") === true &&
          !href.startsWith("//") &&
          !event.metaKey &&
          !event.ctrlKey &&
          !event.shiftKey
        ) {
          event.preventDefault();
          void navigate(href);
        }
      }}
    />
  );
}
