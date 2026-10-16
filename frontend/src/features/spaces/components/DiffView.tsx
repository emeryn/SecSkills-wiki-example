import { useTranslation } from "react-i18next";

export interface DiffRow {
  op: "equal" | "insert" | "delete";
  text: string;
}

/** Line diff; additions and deletions are marked by sign and label, not by color alone. */
export function DiffView({ lines }: { lines: DiffRow[] }) {
  const { t } = useTranslation();
  if (lines.every((line) => line.op === "equal")) {
    return <p className="text-text-muted">{t("history.noDifferences")}</p>;
  }
  return (
    <pre
      className="overflow-x-auto rounded-lg border border-border font-mono text-xs"
      aria-label={t("history.diff")}
    >
      {lines.map((line, index) => (
        <div
          key={index}
          className={
            line.op === "insert"
              ? "bg-success/10 text-success"
              : line.op === "delete"
                ? "bg-danger/10 text-danger line-through decoration-danger/40"
                : "text-text-muted"
          }
        >
          <span aria-hidden className="inline-block w-6 select-none text-center">
            {line.op === "insert" ? "+" : line.op === "delete" ? "−" : " "}
          </span>
          <span className="sr-only">
            {line.op === "insert"
              ? t("history.added")
              : line.op === "delete"
                ? t("history.removed")
                : ""}
          </span>
          {line.text || " "}
        </div>
      ))}
    </pre>
  );
}
