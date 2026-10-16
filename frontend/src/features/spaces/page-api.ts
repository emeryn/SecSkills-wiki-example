import { apiRequest } from "../../lib/api-client";
import type { TreeNode } from "./api";

export interface PageData {
  id: string;
  space_key: string;
  parent_id: string | null;
  slug: string;
  title: string;
  body: string;
  revision_id: string;
  revision_number: number;
  updated_at: string;
  updated_by: string | null;
  ancestors: TreeNode[];
  is_home: boolean;
  favorite: boolean;
}

export interface RevisionSummary {
  id: string;
  number: number;
  title: string;
  message: string;
  author: string | null;
  created_at: string;
  restored_from_id: string | null;
}

export interface RevisionDetail extends RevisionSummary {
  body: string;
}

export interface DiffLine {
  op: "equal" | "insert" | "delete";
  text: string;
  old_number: number | null;
  new_number: number | null;
}

export interface DiffData {
  old: RevisionSummary;
  new: RevisionSummary;
  lines: DiffLine[];
}

export interface PageInput {
  title: string;
  body: string;
  message: string;
}

const base = (space: string) => `/spaces/${space}/pages`;

export const pageKeys = {
  bySlug: (space: string, slug: string) => ["pages", space, "slug", slug] as const,
  revisions: (space: string, id: string, page: number) =>
    ["pages", space, id, "revisions", page] as const,
};

export const pagesApi = {
  bySlug: (space: string, slug: string) =>
    apiRequest<PageData>("GET", `${base(space)}/by-slug/${slug}`),
  create: (space: string, body: PageInput & { parent_id: string | null }, idempotencyKey: string) =>
    apiRequest<PageData>("POST", base(space), { body, idempotencyKey }),
  /** Optimistic locking: rejected with 412 when `revisionId` is no longer current. */
  update: (
    space: string,
    id: string,
    revisionId: string,
    body: PageInput,
    idempotencyKey: string,
  ) =>
    apiRequest<PageData>("PUT", `${base(space)}/${id}`, {
      body,
      idempotencyKey,
      headers: { "If-Match": `"${revisionId}"` },
    }),
  remove: (space: string, id: string) => apiRequest<undefined>("DELETE", `${base(space)}/${id}`),
  move: (space: string, id: string, parentId: string | null, position: number) =>
    apiRequest<PageData>("POST", `${base(space)}/${id}/move`, {
      body: { parent_id: parentId, position },
    }),
  revisions: (space: string, id: string, page: number) =>
    apiRequest<{ items: RevisionSummary[]; total: number; page: number; page_size: number }>(
      "GET",
      `${base(space)}/${id}/revisions?page=${String(page)}&page_size=25`,
    ),
  revision: (space: string, id: string, revisionId: string) =>
    apiRequest<RevisionDetail>("GET", `${base(space)}/${id}/revisions/${revisionId}`),
  diff: (space: string, id: string, revisionId: string, against: string) =>
    apiRequest<DiffData>(
      "GET",
      `${base(space)}/${id}/revisions/${revisionId}/diff?against=${against}`,
    ),
  restoreRevision: (space: string, id: string, revisionId: string) =>
    apiRequest<PageData>("POST", `${base(space)}/${id}/revisions/${revisionId}/restore`),
};
