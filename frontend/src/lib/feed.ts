import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./api-client";

/** Recent changes and favorites: used by the dashboard, the sidebar and page views. */

export interface Change {
  page_id: string;
  space_key: string;
  space_name: string;
  slug: string;
  title: string;
  revision_number: number;
  message: string;
  author: string | null;
  created_at: string;
}

export interface Favorite {
  page_id: string;
  space_key: string;
  space_name: string;
  slug: string;
  title: string;
}

export const feedKeys = {
  recent: (space?: string) => ["recent-changes", space ?? "all"] as const,
  favorites: ["favorites"] as const,
};

export const feedApi = {
  recentChanges: (space?: string, limit = 25) =>
    apiRequest<Change[]>(
      "GET",
      `/recent-changes?limit=${String(limit)}${space !== undefined ? `&space=${space}` : ""}`,
    ),
  favorites: () => apiRequest<Favorite[]>("GET", "/me/favorites"),
  addFavorite: (pageId: string) => apiRequest<undefined>("PUT", `/me/favorites/${pageId}`),
  removeFavorite: (pageId: string) => apiRequest<undefined>("DELETE", `/me/favorites/${pageId}`),
};

export function useFavorites(enabled = true) {
  return useQuery({ queryKey: feedKeys.favorites, queryFn: feedApi.favorites, enabled });
}

export function useRecentChanges(limit = 10) {
  return useQuery({
    queryKey: feedKeys.recent(),
    queryFn: () => feedApi.recentChanges(undefined, limit),
  });
}
