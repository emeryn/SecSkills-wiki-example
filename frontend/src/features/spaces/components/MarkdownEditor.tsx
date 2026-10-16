import { Bold, Code, Heading2, Link2, List, Paperclip, Table } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FormError } from "../../../components/ui/FormError";
import type { TreeNode } from "../api";
import { ACCEPTED_EXTENSIONS } from "../attachments";
import { MarkdownView } from "./MarkdownView";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
  spaceKey: string;
  tree: TreeNode[];
  label: string;
  /** Uploads a file and returns the Markdown to insert; absent while creating a page. */
  onAttach?: (file: File) => Promise<string>;
}

type Edit = (selected: string) => { text: string; cursorOffset?: number };

const ACTIONS: { key: string; icon: ReactNode; edit: Edit; linePrefix?: boolean }[] = [
  {
    key: "heading",
    icon: <Heading2 aria-hidden className="size-4" />,
    edit: (s) => ({ text: `## ${s || "Heading"}` }),
    linePrefix: true,
  },
  {
    key: "bold",
    icon: <Bold aria-hidden className="size-4" />,
    edit: (s) => ({ text: `**${s || "bold"}**` }),
  },
  {
    key: "list",
    icon: <List aria-hidden className="size-4" />,
    edit: (s) => ({
      text: (s || "item")
        .split("\n")
        .map((l) => `- ${l}`)
        .join("\n"),
    }),
    linePrefix: true,
  },
  {
    key: "link",
    icon: <Link2 aria-hidden className="size-4" />,
    edit: (s) => ({ text: `[${s || "text"}](https://)` }),
  },
  {
    key: "code",
    icon: <Code aria-hidden className="size-4" />,
    edit: (s) => ({ text: s.includes("\n") ? `\`\`\`\n${s}\n\`\`\`` : `\`${s || "code"}\`` }),
  },
  {
    key: "table",
    icon: <Table aria-hidden className="size-4" />,
    edit: () => ({ text: "| Column | Column |\n| --- | --- |\n| Cell | Cell |" }),
    linePrefix: true,
  },
];

/** Split view: Markdown source and live preview rendered through the same sanitizer as pages. */
export function MarkdownEditor({
  value,
  onChange,
  onSave,
  spaceKey,
  tree,
  label,
  onAttach,
}: MarkdownEditorProps) {
  const { t } = useTranslation();
  const textarea = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState<unknown>(null);

  const apply = (edit: Edit, linePrefix: boolean | undefined) => {
    const element = textarea.current;
    if (element === null) return;
    const { selectionStart: start, selectionEnd: end } = element;
    const needsNewline = linePrefix === true && start > 0 && value[start - 1] !== "\n";
    const { text } = edit(value.slice(start, end));
    const insert = (needsNewline ? "\n" : "") + text;
    onChange(value.slice(0, start) + insert + value.slice(end));
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + insert.length, start + insert.length);
    });
  };

  return (
    <div className="grid min-h-[60vh] gap-4 lg:grid-cols-2">
      <div className="flex flex-col rounded-lg border border-border">
        <div
          role="toolbar"
          aria-label={t("editor.toolbar")}
          className="flex gap-1 border-b border-border p-1"
        >
          {ACTIONS.map((action) => (
            <button
              key={action.key}
              type="button"
              title={t(`editor.${action.key}`)}
              aria-label={t(`editor.${action.key}`)}
              onClick={() => {
                apply(action.edit, action.linePrefix);
              }}
              className="flex size-8 items-center justify-center rounded-md hover:bg-surface-muted"
            >
              {action.icon}
            </button>
          ))}
          {onAttach !== undefined && (
            <>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file === undefined) return;
                  setAttaching(true);
                  setAttachError(null);
                  onAttach(file)
                    .then((markdown) => {
                      apply(() => ({ text: markdown }), true);
                    })
                    .catch((error: unknown) => {
                      setAttachError(error);
                    })
                    .finally(() => {
                      setAttaching(false);
                    });
                }}
              />
              <button
                type="button"
                title={t("editor.attach")}
                aria-label={t("editor.attach")}
                aria-busy={attaching || undefined}
                disabled={attaching}
                onClick={() => fileInput.current?.click()}
                className="ml-auto flex size-8 items-center justify-center rounded-md hover:bg-surface-muted disabled:opacity-60"
              >
                <Paperclip aria-hidden className="size-4" />
              </button>
            </>
          )}
        </div>
        <FormError error={attachError} />
        <label htmlFor="page-body" className="sr-only">
          {label}
        </label>
        <textarea
          id="page-body"
          ref={textarea}
          value={value}
          spellCheck
          onChange={(event) => {
            onChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              onSave();
            }
          }}
          className="min-h-[50vh] flex-1 resize-none bg-surface p-3 font-mono text-sm outline-none"
        />
      </div>
      <section
        aria-label={t("editor.preview")}
        className="overflow-auto rounded-lg border border-border p-4"
      >
        <MarkdownView source={value} spaceKey={spaceKey} tree={tree} />
      </section>
    </div>
  );
}
