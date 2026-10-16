import { diffLines } from "diff";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import type { PageData } from "../page-api";
import { DiffView, type DiffRow } from "./DiffView";

interface ConflictDialogProps {
  latest: PageData | null;
  mine: { title: string; body: string };
  onKeepMine: () => void;
  onUseTheirs: () => void;
  onClose: () => void;
}

/** Someone saved first (412): show their version against mine and let the user decide. */
export function ConflictDialog({
  latest,
  mine,
  onKeepMine,
  onUseTheirs,
  onClose,
}: ConflictDialogProps) {
  const { t } = useTranslation();
  const rows = useMemo<DiffRow[]>(() => {
    if (latest === null) return [];
    return diffLines(`# ${latest.title}\n${latest.body}`, `# ${mine.title}\n${mine.body}`).flatMap(
      (part) =>
        part.value
          .replace(/\n$/, "")
          .split("\n")
          .map((text) => ({ op: part.added ? "insert" : part.removed ? "delete" : "equal", text })),
    );
  }, [latest, mine]);

  return (
    <Dialog
      open={latest !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      size="lg"
      title={t("editor.conflictTitle")}
      description={t("editor.conflictHelp", {
        author: latest?.updated_by ?? "?",
        number: latest?.revision_number ?? 0,
      })}
    >
      <div className="max-h-[50vh] overflow-auto">
        <DiffView lines={rows} />
      </div>
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button onClick={onUseTheirs}>{t("editor.useTheirs")}</Button>
        <Button variant="primary" onClick={onKeepMine}>
          {t("editor.keepMine")}
        </Button>
      </div>
    </Dialog>
  );
}
