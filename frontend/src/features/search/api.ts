import { apiRequest } from "../../lib/api-client";

export interface SnippetSegment {
  text: string;
  highlight: boolean;
}

export interface SearchHit {
  page_id: string;
  space_key: string;
  space_name: string;
  slug: string;
  title: string;
  snippet: SnippetSegment[];
  updated_at: string;
}

export interface SearchResults {
  items: SearchHit[];
  total: number;
  page: number;
  page_size: number;
}

export const SEARCH_PAGE_SIZE = 20;

export function searchPages(q: string, page: number): Promise<SearchResults> {
  const params = new URLSearchParams({
    q,
    page: String(page),
    page_size: String(SEARCH_PAGE_SIZE),
  });
  return apiRequest<SearchResults>("GET", `/search?${params.toString()}`);
}
