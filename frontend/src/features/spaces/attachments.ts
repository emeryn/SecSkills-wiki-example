import { apiDownload, apiRequest, apiUpload } from "../../lib/api-client";

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  inline: boolean;
  uploaded_by: string | null;
  created_at: string;
  url: string;
}

/** Same limits as the server (backend attachment_service); the server stays the authority. */
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS =
  ".png,.jpg,.jpeg,.gif,.webp,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.odp,.txt,.md,.csv,.log";

export const attachmentKeys = {
  list: (space: string, pageId: string) => ["attachments", space, pageId] as const,
};

export const attachmentsApi = {
  list: (space: string, pageId: string) =>
    apiRequest<Attachment[]>("GET", `/spaces/${space}/pages/${pageId}/attachments`),
  upload: (space: string, pageId: string, file: File) =>
    apiUpload<Attachment>(`/spaces/${space}/pages/${pageId}/attachments`, file),
  remove: (id: string) => apiRequest<undefined>("DELETE", `/attachments/${id}`),
};

export function exportArchive(space: string, pageId?: string) {
  return apiDownload(`/spaces/${space}/export${pageId !== undefined ? `?page=${pageId}` : ""}`);
}

/** Markdown that embeds (images) or links (documents) an attachment. */
export function markdownFor(attachment: Attachment): string {
  const label = attachment.filename.replace(/[[\]]/g, "");
  return attachment.inline ? `![${label}](${attachment.url})` : `[${label}](${attachment.url})`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
