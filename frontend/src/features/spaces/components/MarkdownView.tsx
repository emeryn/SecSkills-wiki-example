import { useMemo } from "react";
import { SanitizedHtml } from "../../../components/ui/SanitizedHtml";
import { normalizeTitle, renderMarkdown } from "../../../lib/markdown";
import type { TreeNode } from "../api";

interface MarkdownViewProps {
  source: string;
  spaceKey: string;
  tree: TreeNode[];
}

/** Rendered page body. `[[Title]]` links resolve against the page titles of the same space. */
export function MarkdownView({ source, spaceKey, tree }: MarkdownViewProps) {
  const html = useMemo(() => {
    const bySlug = new Map(tree.map((node) => [normalizeTitle(node.title), node.slug]));
    return renderMarkdown(source, (title) => {
      const slug = bySlug.get(normalizeTitle(title));
      return slug === undefined ? null : `/spaces/${spaceKey}/pages/${slug}`;
    });
  }, [source, spaceKey, tree]);

  return <SanitizedHtml html={html} />;
}
