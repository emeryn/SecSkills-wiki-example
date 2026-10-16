import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";
import type { TreeNode } from "../api";

interface PageTreeProps {
  spaceKey: string;
  nodes: TreeNode[];
  currentSlug?: string;
}

function childrenOf(nodes: TreeNode[]): Map<string | null, TreeNode[]> {
  const map = new Map<string | null, TreeNode[]>();
  for (const node of nodes) {
    const siblings = map.get(node.parent_id) ?? [];
    siblings.push(node);
    map.set(node.parent_id, siblings);
  }
  for (const siblings of map.values()) siblings.sort((a, b) => a.position - b.position);
  return map;
}

/** Page hierarchy of a space; branches containing the current page start expanded. */
export function PageTree({ spaceKey, nodes, currentSlug }: PageTreeProps) {
  const { t } = useTranslation();
  const tree = useMemo(() => childrenOf(nodes), [nodes]);
  const openPath = useMemo(() => {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const path = new Set<string>();
    let current = nodes.find((node) => node.slug === currentSlug);
    while (current?.parent_id != null) {
      path.add(current.parent_id);
      current = byId.get(current.parent_id);
    }
    return path;
  }, [nodes, currentSlug]);
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const renderLevel = (parentId: string | null, depth: number) => (
    <ul className={depth > 0 ? "ml-3 border-l border-border pl-2" : undefined}>
      {(tree.get(parentId) ?? []).map((node) => {
        const hasChildren = (tree.get(node.id)?.length ?? 0) > 0;
        const open = toggled[node.id] ?? openPath.has(node.id);
        return (
          <li key={node.id}>
            <div className="flex items-center gap-1">
              {hasChildren ? (
                <button
                  type="button"
                  aria-label={
                    open
                      ? t("pages.collapse", { title: node.title })
                      : t("pages.expand", { title: node.title })
                  }
                  aria-expanded={open}
                  onClick={() => {
                    setToggled((current) => ({ ...current, [node.id]: !open }));
                  }}
                  className="flex size-6 shrink-0 items-center justify-center rounded-sm hover:bg-surface-muted"
                >
                  {open ? (
                    <ChevronDown aria-hidden className="size-3.5" />
                  ) : (
                    <ChevronRight aria-hidden className="size-3.5" />
                  )}
                </button>
              ) : (
                <FileText aria-hidden className="mx-1 size-3.5 shrink-0 text-text-muted" />
              )}
              <NavLink
                to={`/spaces/${spaceKey}/pages/${node.slug}`}
                end
                className={({ isActive }) =>
                  `block min-w-0 flex-1 truncate rounded-sm px-1.5 py-1 ${isActive ? "bg-primary/10 font-medium text-primary" : "hover:bg-surface-muted"}`
                }
              >
                {node.title}
              </NavLink>
            </div>
            {hasChildren && open && renderLevel(node.id, depth + 1)}
          </li>
        );
      })}
    </ul>
  );

  return <nav aria-label={t("pages.tree")}>{renderLevel(null, 0)}</nav>;
}
