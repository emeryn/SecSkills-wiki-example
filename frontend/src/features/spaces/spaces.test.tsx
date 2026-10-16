import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture, type Handler } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const space = (role: string) => ({
  key: "eng",
  name: "Engineering",
  description: "",
  visibility: "restricted",
  archived: false,
  home_page_id: "p-home",
  role,
});
const tree = [
  {
    id: "p-home",
    parent_id: null,
    slug: "engineering",
    title: "Engineering",
    position: 0,
    depth: 1,
  },
  {
    id: "p-guide",
    parent_id: "p-home",
    slug: "getting-started",
    title: "Getting Started",
    position: 0,
    depth: 2,
  },
];
const page = (overrides: Record<string, unknown> = {}) => ({
  id: "p-home",
  space_key: "eng",
  parent_id: null,
  slug: "engineering",
  title: "Engineering",
  body: "Read [[Getting Started]] and [[Missing Page]].\n\n<script>alert(1)</script>",
  revision_id: "rev-1",
  revision_number: 1,
  updated_at: "2026-10-14T10:00:00Z",
  updated_by: "erin",
  ancestors: [],
  is_home: true,
  favorite: false,
  ...overrides,
});

function api(role: string, extra: Record<string, Handler> = {}) {
  return mockApi({
    "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
    "GET /api/v1/spaces/eng": () => Response.json(space(role)),
    "GET /api/v1/spaces/eng/pages": () => Response.json(tree),
    "GET /api/v1/spaces/eng/pages/by-slug/engineering": () => Response.json(page()),
    "GET /api/v1/me/favorites": () => Response.json([]),
    "GET /api/v1/recent-changes": () => Response.json([]),
    ...extra,
  });
}

describe("page view", () => {
  it("renders sanitized Markdown with resolved and broken wiki links", async () => {
    api("viewer");
    renderAt("/spaces/eng/pages/engineering");
    const link = await screen.findByRole("link", { name: "Getting Started", hidden: false });
    expect(link.getAttribute("href")).toBe("/spaces/eng/pages/getting-started");
    expect(document.querySelector(".wiki-link-broken")?.textContent).toBe("Missing Page");
    expect(document.querySelector(".wiki-content script")).toBeNull();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeDefined();
  });

  it("redirects the space root to its home page", async () => {
    api("viewer");
    const router = renderAt("/spaces/eng");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/spaces/eng/pages/engineering");
    });
  });

  it("hides editing actions from viewers", async () => {
    api("viewer");
    renderAt("/spaces/eng/pages/engineering");
    await screen.findByRole("heading", { level: 1, name: "Engineering" });
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New page" })).toBeNull();
  });
});

describe("editor", () => {
  it("saves with Ctrl+S and If-Match, then resolves a conflict by keeping my version", async () => {
    // Someone else saves revision 2 while we edit revision 1.
    let current = page();
    const puts: string[] = [];
    api("editor", {
      "GET /api/v1/spaces/eng/pages/by-slug/engineering": () => Response.json(current),
      "PUT /api/v1/spaces/eng/pages/p-home": (init) => {
        const ifMatch = new Headers(init?.headers).get("If-Match") ?? "";
        puts.push(ifMatch);
        if (ifMatch !== `"${current.revision_id}"`) {
          return Response.json(
            { error: { code: "STALE_REVISION", message: "x", request_id: "r" } },
            { status: 412 },
          );
        }
        current = page({ revision_id: "rev-3", revision_number: 3, body: "mine" });
        return Response.json(current);
      },
    });
    const router = renderAt("/spaces/eng/pages/engineering/edit");
    const textarea = await screen.findByLabelText("Content (Markdown)");
    current = page({ revision_id: "rev-2", revision_number: 2, body: "theirs", updated_by: "zoe" });
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "mine");
    await userEvent.keyboard("{Control>}s{/Control}");

    expect(
      await screen.findByRole("heading", { name: /changed while you were editing/ }),
    ).toBeDefined();
    expect(screen.getByText(/zoe saved revision 2/)).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "Save my version" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/spaces/eng/pages/engineering");
    });
    expect(puts).toEqual(['"rev-1"', '"rev-2"']);
  });
});
