import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquareText, Square, SendHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { PageHeader } from "../../../components/ui/PageHeader";
import { SanitizedHtml } from "../../../components/ui/SanitizedHtml";
import { Skeleton } from "../../../components/ui/Skeleton";
import { ApiError } from "../../../lib/api-client";
import { renderMarkdown } from "../../../lib/markdown";
import { askApi, createSseParser, type AskSource, type HistoryMessage } from "../api";

interface Turn {
  question: string;
  answer: string;
  sources: AskSource[];
  status: "streaming" | "done" | "stopped" | "error";
  error?: string;
}

const HISTORY_TURNS = 3;
const MAX_HISTORY_CHARS = 4000;

function history(turns: Turn[]): HistoryMessage[] {
  return turns
    .filter((turn) => turn.status === "done")
    .slice(-HISTORY_TURNS)
    .flatMap((turn) => [
      { role: "user" as const, content: turn.question.slice(0, MAX_HISTORY_CHARS) },
      { role: "assistant" as const, content: turn.answer.slice(0, MAX_HISTORY_CHARS) },
    ]);
}

/** Answer as sanitized Markdown: no raw HTML, no remote images, links checked. */
function Answer({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text, () => null), [text]);
  return <SanitizedHtml html={html} />;
}

function TurnView({ turn }: { turn: Turn }) {
  const { t } = useTranslation();
  return (
    <article className="space-y-3 border-b border-border pb-6">
      <p className="font-medium">{turn.question}</p>
      {turn.answer === "" && turn.status === "streaming" ? (
        <div aria-busy className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <span className="sr-only">{t("ask.thinking")}</span>
        </div>
      ) : (
        <Answer text={turn.answer} />
      )}
      {turn.status === "stopped" && <p className="text-xs text-text-muted">{t("ask.stopped")}</p>}
      {turn.error !== undefined && (
        <p role="alert" className="text-danger">
          {turn.error}
        </p>
      )}
      {turn.sources.length > 0 && (
        <div>
          <p className="text-xs font-semibold tracking-wide text-text-muted uppercase">
            {t("ask.sources")}
          </p>
          <ol className="mt-1 space-y-1">
            {turn.sources.map((source) => (
              <li key={source.id}>
                <span className="mr-1 text-text-muted">[{source.id}]</span>
                <Link
                  to={`/spaces/${source.space_key}/pages/${source.slug}`}
                  className="text-primary hover:underline"
                >
                  {source.title}
                </Link>
              </li>
            ))}
          </ol>
        </div>
      )}
    </article>
  );
}

export function AskPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["ask", "status"], queryFn: askApi.status });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const controller = useRef<AbortController | null>(null);
  const streaming = turns.at(-1)?.status === "streaming";

  useEffect(() => () => controller.current?.abort(), []);

  const update = (change: (turn: Turn) => Turn) => {
    setTurns((current) => [...current.slice(0, -1), change(current.at(-1) as Turn)]);
  };

  const errorMessage = (error: unknown) => {
    const code = error instanceof ApiError ? error.code : "NETWORK_ERROR";
    const key = `ask.errors.${code}`;
    return t(key) !== key ? t(key) : t("errors.unexpectedMessage");
  };

  const submit = async () => {
    const text = question.trim();
    if (text === "" || streaming) return;
    const abort = new AbortController();
    controller.current = abort;
    const previous = history(turns);
    setQuestion("");
    setTurns((current) => [
      ...current,
      { question: text, answer: "", sources: [], status: "streaming" },
    ]);
    try {
      const response = await askApi.ask(text, previous, abort.signal);
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      const parse = createSseParser((event) => {
        if (event.event === "sources") update((turn) => ({ ...turn, sources: event.data }));
        else if (event.event === "token")
          update((turn) => ({ ...turn, answer: turn.answer + event.data.text }));
        else if (event.event === "done") update((turn) => ({ ...turn, status: "done" }));
        else update((turn) => ({ ...turn, status: "error", error: t("ask.errors.interrupted") }));
      });
      for (;;) {
        const chunk = await reader?.read();
        if (chunk === undefined || chunk.done) break;
        parse(decoder.decode(chunk.value, { stream: true }));
      }
      update((turn) => (turn.status === "streaming" ? { ...turn, status: "done" } : turn));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        update((turn) => ({ ...turn, status: "stopped" }));
      } else {
        update((turn) => ({ ...turn, status: "error", error: errorMessage(error) }));
      }
    } finally {
      controller.current = null;
      await queryClient.invalidateQueries({ queryKey: ["ask", "status"] });
    }
  };

  const header = (
    <PageHeader
      title={t("ask.title")}
      breadcrumb={[{ label: t("nav.home"), to: "/" }, { label: t("ask.title") }]}
      secondaryActions={
        turns.length > 0 ? (
          <Button
            disabled={streaming}
            onClick={() => {
              setTurns([]);
            }}
          >
            {t("ask.newConversation")}
          </Button>
        ) : undefined
      }
    />
  );

  if (status.isError) {
    return (
      <>
        {header}
        <ErrorState error={status.error} onRetry={() => void status.refetch()} />
      </>
    );
  }
  if (status.data?.enabled === false) {
    return (
      <>
        {header}
        <EmptyState
          icon={MessageSquareText}
          title={t("ask.disabledTitle")}
          description={t("ask.disabledHelp")}
        />
      </>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      {header}
      {turns.length === 0 ? (
        <p className="text-text-muted">{t("ask.intro")}</p>
      ) : (
        <div aria-live="polite" className="space-y-6">
          {turns.map((turn, index) => (
            <TurnView key={String(index)} turn={turn} />
          ))}
        </div>
      )}
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="ask-question" className="sr-only">
          {t("ask.question")}
        </label>
        <textarea
          id="ask-question"
          rows={3}
          maxLength={2000}
          value={question}
          placeholder={t("ask.placeholder")}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              void submit();
            }
          }}
          className="w-full rounded-md border border-border bg-surface px-3 py-2"
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-text-muted">
            {status.data !== undefined &&
              t("ask.quota", {
                used: status.data.tokens_used_today,
                quota: status.data.daily_token_quota,
              })}
          </p>
          {streaming ? (
            <Button
              icon={<Square aria-hidden className="size-4" />}
              onClick={() => {
                controller.current?.abort();
              }}
            >
              {t("ask.stop")}
            </Button>
          ) : (
            <Button
              type="submit"
              variant="primary"
              disabled={question.trim() === ""}
              icon={<SendHorizontal aria-hidden className="size-4" />}
            >
              {t("ask.send")}
            </Button>
          )}
        </div>
        <p className="text-xs text-text-muted">{t("ask.disclaimer")}</p>
      </form>
    </div>
  );
}
