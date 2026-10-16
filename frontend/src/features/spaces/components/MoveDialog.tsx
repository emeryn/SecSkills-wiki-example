import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import { SelectField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { spaceKeys, type TreeNode } from "../api";
import { pagesApi, type PageData } from "../page-api";

const MAX_DEPTH = 5;

interface MoveDialogProps {
  page: PageData | null;
  tree: TreeNode[];
  onClose: (moved: PageData | null) => void;
}

/** Move a page (and its subtree) under another parent; the server re-checks depth and cycles. */
export function MoveDialog({ page, tree, onClose }: MoveDialogProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [parent, setParent] = useState("");

  const options = useMemo(() => {
    if (page === null) return [];
    const excluded = new Set([page.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const node of tree) {
        if (node.parent_id !== null && excluded.has(node.parent_id) && !excluded.has(node.id)) {
          excluded.add(node.id);
          grew = true;
        }
      }
    }
    return tree
      .filter((node) => !excluded.has(node.id) && node.depth < MAX_DEPTH)
      .map((node) => ({ value: node.id, label: `${"— ".repeat(node.depth - 1)}${node.title}` }));
  }, [page, tree]);

  const move = useMutation({
    mutationFn: () => {
      const parentId = parent === "" ? null : parent;
      const siblings = tree.filter((node) => node.parent_id === parentId && node.id !== page?.id);
      return pagesApi.move(page?.space_key ?? "", page?.id ?? "", parentId, siblings.length);
    },
    onSuccess: async (moved) => {
      await queryClient.invalidateQueries({ queryKey: spaceKeys.tree(moved.space_key) });
      onClose(moved);
    },
  });

  return (
    <Dialog
      open={page !== null}
      onOpenChange={(open) => {
        if (!open) onClose(null);
      }}
      title={t("pages.moveTitle", { title: page?.title ?? "" })}
      description={t("pages.moveHelp")}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          move.mutate();
        }}
      >
        <SelectField
          label={t("pages.newParent")}
          value={parent}
          onChange={(event) => {
            setParent(event.target.value);
          }}
          options={[{ value: "", label: t("pages.topLevel") }, ...options]}
        />
        <FormError error={move.error} />
        <div className="flex justify-end gap-2">
          <Button
            onClick={() => {
              onClose(null);
            }}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={move.isPending}>
            {t("pages.move")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
