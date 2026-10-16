import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../../lib/api-client";

export type SpaceRole = "viewer" | "editor" | "space_admin";
export type Visibility = "restricted" | "internal";

export interface Space {
  key: string;
  name: string;
  description: string;
  visibility: Visibility;
  archived: boolean;
  home_page_id: string | null;
  role: SpaceRole | null;
}

export interface AdminSpace extends Space {
  member_count: number;
  created_at: string;
}

export interface TreeNode {
  id: string;
  parent_id: string | null;
  slug: string;
  title: string;
  position: number;
  depth: number;
}

export interface Member {
  principal_type: "user" | "group";
  principal_id: string;
  name: string;
  role: SpaceRole;
}

export interface TrashItem {
  id: string;
  title: string;
  deleted_at: string;
  deleted_by: string | null;
  pages: number;
  purge_after: string;
}

const ROLE_RANK: Record<SpaceRole, number> = { viewer: 1, editor: 2, space_admin: 3 };

export function canRole(role: SpaceRole | null | undefined, needed: SpaceRole): boolean {
  return role != null && ROLE_RANK[role] >= ROLE_RANK[needed];
}

export const spaceKeys = {
  all: ["spaces"] as const,
  space: (key: string) => ["spaces", key] as const,
  tree: (key: string) => ["spaces", key, "tree"] as const,
  members: (key: string) => ["spaces", key, "members"] as const,
  trash: (key: string) => ["spaces", key, "trash"] as const,
};

export const spacesApi = {
  list: () => apiRequest<Space[]>("GET", "/spaces"),
  get: (key: string) => apiRequest<Space>("GET", `/spaces/${key}`),
  create: (
    body: { name: string; description: string; visibility: Visibility; space_admin_id: string },
    idempotencyKey: string,
  ) => apiRequest<Space>("POST", "/spaces", { body, idempotencyKey }),
  update: (
    key: string,
    body: Partial<{ name: string; description: string; visibility: Visibility; archived: boolean }>,
    idempotencyKey: string,
  ) => apiRequest<Space>("PATCH", `/spaces/${key}`, { body, idempotencyKey }),
  tree: (key: string) => apiRequest<TreeNode[]>("GET", `/spaces/${key}/pages`),
  members: (key: string) => apiRequest<Member[]>("GET", `/spaces/${key}/members`),
  setMember: (key: string, type: "user" | "group", id: string, role: SpaceRole) =>
    apiRequest<undefined>("PUT", `/spaces/${key}/members/${type}/${id}`, { body: { role } }),
  removeMember: (key: string, type: "user" | "group", id: string) =>
    apiRequest<undefined>("DELETE", `/spaces/${key}/members/${type}/${id}`),
  principals: (key: string, q: string) =>
    apiRequest<Omit<Member, "role">[]>(
      "GET",
      `/spaces/${key}/principals?q=${encodeURIComponent(q)}`,
    ),
  trash: (key: string) => apiRequest<TrashItem[]>("GET", `/spaces/${key}/trash`),
  restore: (key: string, pageId: string) =>
    apiRequest<TreeNode>("POST", `/spaces/${key}/trash/${pageId}/restore`),
  purge: (key: string, pageId: string) =>
    apiRequest<undefined>("DELETE", `/spaces/${key}/trash/${pageId}`),
  adminList: () => apiRequest<AdminSpace[]>("GET", "/admin/spaces"),
};

export function useSpace(key: string) {
  return useQuery({ queryKey: spaceKeys.space(key), queryFn: () => spacesApi.get(key) });
}

export function useTree(key: string, enabled = true) {
  return useQuery({ queryKey: spaceKeys.tree(key), queryFn: () => spacesApi.tree(key), enabled });
}
