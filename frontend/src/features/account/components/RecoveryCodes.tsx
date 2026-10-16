import { Copy, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { useToast } from "../../../components/ui/Toast";
import { saveBlob } from "../../../lib/download";

/** Shown once after enrollment or regeneration; the server only keeps hashes. */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  const { t } = useTranslation();
  const toast = useToast();
  const text = codes.join("\n");
  return (
    <div className="space-y-3 rounded-lg border border-border p-4">
      <p className="font-medium">{t("account.recoveryCodesTitle")}</p>
      <p className="text-text-muted">{t("account.recoveryCodesHelp")}</p>
      <ul className="grid grid-cols-2 gap-1 font-mono">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button
          icon={<Copy aria-hidden className="size-4" />}
          onClick={() => {
            void navigator.clipboard.writeText(text).then(() => {
              toast(t("common.copied"));
            });
          }}
        >
          {t("common.copy")}
        </Button>
        <Button
          icon={<Download aria-hidden className="size-4" />}
          onClick={() => {
            saveBlob(new Blob([text + "\n"], { type: "text/plain" }), "wiki-recovery-codes.txt");
          }}
        >
          {t("common.download")}
        </Button>
      </div>
    </div>
  );
}
