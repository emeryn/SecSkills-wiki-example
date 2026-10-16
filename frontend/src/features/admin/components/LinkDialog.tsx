import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import { useToast } from "../../../components/ui/Toast";
import { formatDateTime } from "../../../lib/format";
import type { Link } from "../api";

/** Shows an invitation or reset link once; it is not retrievable afterwards. */
export function LinkDialog({
  link,
  title,
  onClose,
}: {
  link: Link | null;
  title: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  return (
    <Dialog
      open={link !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      description={t("admin.linkHelp", { date: formatDateTime(link?.expires_at) })}
    >
      <div className="space-y-4">
        <input
          readOnly
          aria-label={title}
          value={link?.url ?? ""}
          onFocus={(event) => {
            event.target.select();
          }}
          className="h-9 w-full rounded-md border border-border bg-surface-muted px-3 font-mono text-xs"
        />
        <div className="flex justify-end">
          <Button
            variant="primary"
            icon={<Copy aria-hidden className="size-4" />}
            onClick={() => {
              void navigator.clipboard.writeText(link?.url ?? "").then(() => {
                toast(t("common.copied"));
              });
            }}
          >
            {t("common.copy")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
