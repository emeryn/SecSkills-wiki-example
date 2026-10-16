import { apiRequest, apiStream } from "../../lib/api-client";

export interface AskStatus {
  enabled: boolean;
  daily_token_quota: number;
  tokens_used_today: number;
}

export interface AskSource {
  id: number;
  title: string;
  space_key: string;
  slug: string;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export type AskEvent =
  | { event: "sources"; data: AskSource[] }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { prompt_tokens: number; completion_tokens: number } }
  | { event: "error"; data: { code: string; message: string } };

export const askApi = {
  status: () => apiRequest<AskStatus>("GET", "/ask/status"),
  ask: (question: string, history: HistoryMessage[], signal: AbortSignal) =>
    apiStream("/ask", { question, history }, signal),
};

/** Incremental parser for `event:` / `data:` blocks separated by a blank line. */
export function createSseParser(onEvent: (event: AskEvent) => void) {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk;
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let name = "";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (name !== "" && data !== "") {
        onEvent({ event: name, data: JSON.parse(data) as unknown } as AskEvent);
      }
      boundary = buffer.indexOf("\n\n");
    }
  };
}
