import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const results = {
  items: [
    {
      page_id: "p1",
      space_key: "eng",
      space_name: "Engineering",
      slug: "falcon",
      title: "Falcon",
      snippet: [
        { text: "<img src=x onerror=alert(1)> the ", highlight: false },
        { text: "falcon", highlight: true },
        { text: " project", highlight: false },
      ],
      updated_at: "2026-10-14T10:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

function api() {
  return mockApi({
    "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
    "GET /api/v1/me/favorites": () => Response.json([]),
    "GET /api/v1/search": () => Response.json(results),
    "GET /api/v1/recent-changes": () => Response.json([]),
    "GET /api/v1/spaces": () => Response.json([]),
  });
}

describe("search", () => {
  it("renders snippets as text with highlighted terms", async () => {
    const calls = api();
    renderAt("/search?q=falcon");
    const mark = await screen.findByText("falcon", { selector: "mark" });
    expect(mark.tagName).toBe("MARK");
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeDefined();
    expect(document.querySelector("main img")).toBeNull();
    const searchCall = calls.calls.find((call) => call.path === "/api/v1/search");
    expect(searchCall).toBeDefined();
  });

  it("focuses the global search with Ctrl+K and navigates on submit", async () => {
    api();
    const router = renderAt("/");
    await screen.findByRole("heading", { level: 1, name: "Dashboard" });
    await userEvent.keyboard("{Control>}k{/Control}");
    const box = screen.getByRole("searchbox", { name: "Search pages" });
    expect(document.activeElement).toBe(box);
    await userEvent.type(box, "falcon wings{Enter}");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/search");
    });
    expect(router.state.location.search).toBe("?q=falcon%20wings");
  });
});
