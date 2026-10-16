import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import type StateInline from "markdown-it/lib/rules_inline/state_inline.mjs";

/**
 * Markdown → sanitized HTML. Stored XSS is the primary risk of a wiki, so every layer refuses:
 * raw HTML is disabled in the parser, link schemes are allowlisted, DOMPurify sanitizes the
 * output (returned as TrustedHTML under the CSP), remote images never load and external links
 * open with `rel="noopener noreferrer"`.
 */

/** Resolves `[[Title]]` to an in-app path, or null when no such page exists (broken link). */
export type WikiLinkResolver = (title: string) => string | null;

// Same-origin paths (single leading slash), anchors, http(s) and mailto. No javascript:, data:…
const SAFE_URL = /^(?:https?:\/\/|mailto:|\/(?![/\\])|#)/i;
const ATTACHMENT_SRC = /^\/api\/v1\/attachments\/[0-9a-f-]{36}$/i;
const WIKI_LINK_MAX = 400;

export function normalizeTitle(title: string): string {
  return title.normalize("NFKC").toLowerCase().trim();
}

function wikiLinkRule(resolve: WikiLinkResolver) {
  return (state: StateInline, silent: boolean): boolean => {
    const start = state.pos;
    if (state.src.charCodeAt(start) !== 0x5b || state.src.charCodeAt(start + 1) !== 0x5b)
      return false;
    const end = state.src.indexOf("]]", start + 2);
    if (end < 0 || end - start > WIKI_LINK_MAX) return false;
    const inner = state.src.slice(start + 2, end);
    if (inner.trim() === "" || inner.includes("\n") || inner.includes("[")) return false;
    if (!silent) {
      const [target = "", label] = inner.split("|", 2);
      const text = (label ?? target).trim();
      const href = resolve(target.trim());
      if (href !== null) {
        const open = state.push("link_open", "a", 1);
        open.attrs = [
          ["href", href],
          ["class", "wiki-link"],
        ];
        state.push("text", "", 0).content = text;
        state.push("link_close", "a", -1);
      } else {
        const broken = state.push("wiki_link_broken", "span", 0);
        broken.content = text;
        broken.meta = { target: target.trim() };
      }
    }
    state.pos = end + 2;
    return true;
  };
}

function createParser(resolve: WikiLinkResolver): MarkdownIt {
  const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
  md.validateLink = (url: string) => SAFE_URL.test(url.trim());
  md.inline.ruler.before("link", "wiki_link", wikiLinkRule(resolve));
  md.renderer.rules.wiki_link_broken = (tokens, index) => {
    const token = tokens[index];
    const text = md.utils.escapeHtml(token?.content ?? "");
    return `<span class="wiki-link-broken" title="Page not found">${text}</span>`;
  };
  return md;
}

let hooksInstalled = false;

function installHooks(): void {
  if (hooksInstalled) return;
  hooksInstalled = true;
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      const href = node.getAttribute("href") ?? "";
      if (!SAFE_URL.test(href)) {
        node.removeAttribute("href");
      } else if (/^(?:https?:\/\/|mailto:)/i.test(href)) {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    }
    if (node.tagName === "IMG") {
      const src = node.getAttribute("src") ?? "";
      if (!ATTACHMENT_SRC.test(src)) {
        // Remote images are never loaded (tracking, exfiltration): keep the alt text only.
        node.removeAttribute("src");
        node.setAttribute("data-blocked", "remote");
        node.setAttribute("title", "Remote image not loaded");
      }
      node.setAttribute("loading", "lazy");
      node.removeAttribute("srcset");
    }
  });
}

export type SafeHtml = TrustedHTML | string;

export function renderMarkdown(source: string, resolve: WikiLinkResolver): SafeHtml {
  installHooks();
  const html = createParser(resolve).render(source);
  return DOMPurify.sanitize(html, {
    RETURN_TRUSTED_TYPE: true,
    ALLOWED_URI_REGEXP: SAFE_URL,
    FORBID_TAGS: [
      "style",
      "form",
      "input",
      "button",
      "textarea",
      "select",
      "iframe",
      "object",
      "embed",
      "svg",
      "math",
    ],
    FORBID_ATTR: ["style", "srcset", "formaction", "xlink:href"],
    ALLOW_DATA_ATTR: false,
    ADD_ATTR: ["target"],
  });
}
