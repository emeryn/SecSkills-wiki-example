import { describe, expect, it } from "vitest";
import { renderMarkdown, type WikiLinkResolver } from "./markdown";

const pages: Record<string, string> = { "getting started": "/spaces/eng/pages/getting-started" };
const resolve: WikiLinkResolver = (title) => pages[title.toLowerCase()] ?? null;

function dom(source: string): HTMLElement {
  // jsdom has no Trusted Types: the sanitizer returns a plain string there.
  const html = renderMarkdown(source, resolve) as string;
  return new DOMParser().parseFromString(html, "text/html").body;
}

describe("renderMarkdown — XSS corpus", () => {
  it.each([
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg onload=alert(1)>",
    "<iframe src=//evil.example></iframe>",
    '<a href="javascript:alert(1)">x</a>',
    "<div style=\"background:url('javascript:alert(1)')\">x</div>",
  ])("raw HTML is rendered as text: %s", (source) => {
    const container = dom(source);
    expect(container.querySelector("script, img, svg, iframe, a, div")).toBeNull();
    expect(container.textContent).toContain(source.slice(0, 5));
  });

  it.each([
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](  javascript:alert(1))",
    "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
    "[x](vbscript:msgbox)",
    "[x](//evil.example/steal)",
    "<javascript:alert(1)>",
  ])("dangerous link schemes are dropped: %s", (source) => {
    const anchor = dom(source).querySelector("a");
    expect(anchor?.getAttribute("href") ?? null).toBeNull();
  });

  it.each([String.raw`[x](/\evil.example)`, "[x](/%5C%5Cevil.example)", "[x](/\t/evil.example)"])(
    "slash tricks stay on the same origin: %s",
    (source) => {
      const href = dom(source).querySelector("a")?.getAttribute("href");
      if (href != null) {
        expect(new URL(href, "https://wiki.example.com").origin).toBe("https://wiki.example.com");
      }
    },
  );

  it("does not load remote images", () => {
    const image = dom("![tracker](https://evil.example/pixel.png)").querySelector("img");
    expect(image?.getAttribute("src")).toBeNull();
    expect(image?.getAttribute("data-blocked")).toBe("remote");
    expect(image?.getAttribute("alt")).toBe("tracker");
  });

  it("does not load data: images either", () => {
    const image = dom("![x](data:image/png;base64,AAAA)").querySelector("img");
    expect(image?.getAttribute("src") ?? null).toBeNull();
  });

  it("keeps same-origin attachment images", () => {
    const src = "/api/v1/attachments/0b3a3c8e-1f2a-4c3b-9d4e-5f6a7b8c9d0e";
    expect(dom(`![diagram](${src})`).querySelector("img")?.getAttribute("src")).toBe(src);
  });

  it("opens external links safely", () => {
    const anchor = dom("[docs](https://example.com/docs)").querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("https://example.com/docs");
    expect(anchor?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(anchor?.getAttribute("target")).toBe("_blank");
  });

  it("keeps internal links in the same tab", () => {
    const anchor = dom("[home](/spaces/eng)").querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("/spaces/eng");
    expect(anchor?.hasAttribute("target")).toBe(false);
  });
});

describe("renderMarkdown — wiki links", () => {
  it("resolves [[Page title]] within the space", () => {
    const anchor = dom("See [[Getting Started]].").querySelector("a.wiki-link");
    expect(anchor?.getAttribute("href")).toBe("/spaces/eng/pages/getting-started");
    expect(anchor?.textContent).toBe("Getting Started");
  });

  it("supports a label", () => {
    const anchor = dom("[[Getting Started|the guide]]").querySelector("a");
    expect(anchor?.textContent).toBe("the guide");
  });

  it("highlights broken links without leaking anything", () => {
    const broken = dom("[[Secret <b>roadmap</b>]]").querySelector(".wiki-link-broken");
    expect(broken?.textContent).toBe("Secret <b>roadmap</b>");
    expect(broken?.querySelector("b")).toBeNull();
  });

  it("is not triggered inside code", () => {
    expect(dom("`[[Getting Started]]`").querySelector("a")).toBeNull();
  });
});
