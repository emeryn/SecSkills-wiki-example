import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  size?: "md" | "lg";
}

/**
 * Modal dialog on the native `<dialog>` element: `showModal()` traps focus, makes the page inert
 * and closes on Esc, without injecting styles at runtime (the CSP forbids inline styles).
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  size = "md",
}: DialogProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description !== undefined ? descriptionId : undefined}
      onClose={() => {
        if (open) onOpenChange(false);
      }}
      className={`m-auto w-[calc(100%-2rem)] ${size === "lg" ? "max-w-3xl" : "max-w-md"} rounded-lg border border-border bg-surface-raised p-6 text-text shadow-raised backdrop:bg-black/40`}
    >
      {open && (
        <>
          <div className="mb-4 flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h2 id={titleId} className="text-lg font-semibold">
                {title}
              </h2>
              {description !== undefined && (
                <p id={descriptionId} className="text-text-muted">
                  {description}
                </p>
              )}
            </div>
            <button
              type="button"
              aria-label={t("common.close")}
              onClick={() => {
                onOpenChange(false);
              }}
              className="flex size-8 shrink-0 items-center justify-center rounded-md hover:bg-surface-muted"
            >
              <X aria-hidden className="size-4" />
            </button>
          </div>
          {children}
        </>
      )}
    </dialog>
  );
}
