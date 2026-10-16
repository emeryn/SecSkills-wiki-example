import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, FileText, Image as ImageIcon, Paperclip, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { FormError } from "../../../components/ui/FormError";
import { useToast } from "../../../components/ui/Toast";
import { ApiError } from "../../../lib/api-client";
import { formatDateTime } from "../../../lib/format";
import {
  ACCEPTED_EXTENSIONS,
  MAX_ATTACHMENT_BYTES,
  attachmentKeys,
  attachmentsApi,
  formatSize,
  markdownFor,
  type Attachment,
} from "../attachments";

interface AttachmentsSectionProps {
  spaceKey: string;
  pageId: string;
  canEdit: boolean;
}

/** Files of a page: download, copy the Markdown to embed them, upload and delete (editors). */
export function AttachmentsSection({ spaceKey, pageId, canEdit }: AttachmentsSectionProps) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [tooLarge, setTooLarge] = useState(false);
  const [deleting, setDeleting] = useState<Attachment | null>(null);
  const list = useQuery({
    queryKey: attachmentKeys.list(spaceKey, pageId),
    queryFn: () => attachmentsApi.list(spaceKey, pageId),
  });
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: attachmentKeys.list(spaceKey, pageId) });
  const upload = useMutation({
    mutationFn: (file: File) => attachmentsApi.upload(spaceKey, pageId, file),
    onSuccess: async () => {
      toast(t("attachments.uploaded"));
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (attachment: Attachment) => attachmentsApi.remove(attachment.id),
    onSuccess: async () => {
      setDeleting(null);
      await refresh();
    },
  });
  const rejection =
    upload.error instanceof ApiError && upload.error.code === "ATTACHMENT_REJECTED"
      ? upload.error
      : null;

  return (
    <section
      aria-labelledby="attachments-heading"
      className="mt-8 space-y-3 border-t border-border pt-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="attachments-heading" className="flex items-center gap-2 text-base font-semibold">
          <Paperclip aria-hidden className="size-4" />
          {t("attachments.title")}
        </h2>
        {canEdit && (
          <>
            <input
              ref={input}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              className="sr-only"
              aria-label={t("attachments.choose")}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file === undefined) return;
                setTooLarge(file.size > MAX_ATTACHMENT_BYTES);
                if (file.size <= MAX_ATTACHMENT_BYTES) upload.mutate(file);
              }}
            />
            <Button loading={upload.isPending} onClick={() => input.current?.click()}>
              {t("attachments.upload")}
            </Button>
          </>
        )}
      </div>
      {tooLarge && (
        <p role="alert" className="text-danger">
          {t("attachments.tooLarge")}
        </p>
      )}
      {rejection !== null ? (
        <p role="alert" className="text-danger">
          {rejection.message}
        </p>
      ) : (
        <FormError error={upload.error ?? remove.error} />
      )}
      {list.data !== undefined && list.data.length === 0 && (
        <p className="text-text-muted">{t("attachments.none")}</p>
      )}
      {list.data !== undefined && list.data.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {list.data.map((attachment) => (
            <li key={attachment.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
              {attachment.inline ? (
                <ImageIcon aria-hidden className="size-4 text-text-muted" />
              ) : (
                <FileText aria-hidden className="size-4 text-text-muted" />
              )}
              <a
                href={attachment.url}
                download={attachment.filename}
                className="min-w-0 flex-1 truncate text-primary hover:underline"
              >
                {attachment.filename}
              </a>
              <span className="text-xs text-text-muted">
                {formatSize(attachment.size_bytes)} · {attachment.uploaded_by ?? "—"} ·{" "}
                {formatDateTime(attachment.created_at)}
              </span>
              <span className="flex gap-1">
                <Button
                  variant="ghost"
                  aria-label={t("attachments.copyMarkdown", { name: attachment.filename })}
                  icon={<Copy aria-hidden className="size-4" />}
                  onClick={() => {
                    void navigator.clipboard.writeText(markdownFor(attachment)).then(() => {
                      toast(t("common.copied"));
                    });
                  }}
                />
                <a
                  href={attachment.url}
                  download={attachment.filename}
                  aria-label={t("attachments.download", { name: attachment.filename })}
                  className="flex size-9 items-center justify-center rounded-md hover:bg-surface-muted"
                >
                  <Download aria-hidden className="size-4" />
                </a>
                {canEdit && (
                  <Button
                    variant="ghost"
                    aria-label={t("attachments.delete", { name: attachment.filename })}
                    icon={<Trash2 aria-hidden className="size-4" />}
                    onClick={() => {
                      setDeleting(attachment);
                    }}
                  />
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("attachments.confirmDelete", { name: deleting?.filename ?? "" })}
        description={t("attachments.confirmDeleteHelp")}
        confirmLabel={t("common.delete")}
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting !== null) remove.mutate(deleting);
        }}
      />
    </section>
  );
}
