import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { ApiError, newIdempotencyKey } from "../../../lib/api-client";
import { useUnsavedChangesWarning } from "../../../lib/unsaved-changes";
import { spaceKeys } from "../api";
import { ConflictDialog } from "../components/ConflictDialog";
import { attachmentsApi, markdownFor } from "../attachments";
import { MarkdownEditor } from "../components/MarkdownEditor";
import { pageKeys, pagesApi, type PageData } from "../page-api";
import { useSpaceContext } from "./SpaceLayout";

const TITLE_MAX = 200;
const MESSAGE_MAX = 500;

/** Create (`/spaces/:space/new?parent=`) or edit (`.../pages/:slug/edit`) a page. */
export function PageEditPage({ mode }: { mode: "create" | "edit" }) {
  const { space } = useSpaceContext();
  const { slug = "" } = useParams();
  const existing = useQuery({
    queryKey: pageKeys.bySlug(space.key, slug),
    queryFn: () => pagesApi.bySlug(space.key, slug),
    enabled: mode === "edit",
  });
  if (mode === "create") return <PageEditor initial={null} />;
  if (existing.data === undefined) {
    return existing.isError ? (
      <FormError error={existing.error} />
    ) : (
      <Skeleton className="h-96 w-full" />
    );
  }
  // The form is seeded once from the loaded revision; later refetches do not overwrite edits.
  return <PageEditor key={existing.data.id} initial={existing.data} />;
}

function PageEditor({ initial }: { initial: PageData | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { space, tree } = useSpaceContext();
  const [params] = useSearchParams();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [message, setMessage] = useState("");
  const [baseRevision, setBaseRevision] = useState<string | null>(initial?.revision_id ?? null);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState<PageData | null>(null);
  const key = useRef(newIdempotencyKey());
  const release = useUnsavedChangesWarning(dirty);
  const mode = initial === null ? "create" : "edit";

  const save = useMutation({
    mutationFn: (revision: string | null) => {
      const input = { title, body, message };
      return initial === null
        ? pagesApi.create(space.key, { ...input, parent_id: params.get("parent") }, key.current)
        : pagesApi.update(space.key, initial.id, revision ?? "", input, key.current);
    },
    onSuccess: async (page) => {
      key.current = newIdempotencyKey();
      release();
      setDirty(false);
      queryClient.setQueryData(pageKeys.bySlug(space.key, page.slug), page);
      await queryClient.invalidateQueries({ queryKey: spaceKeys.tree(space.key) });
      await queryClient.invalidateQueries({ queryKey: ["recent-changes"] });
      toast(t("editor.saved"));
      await navigate(`/spaces/${space.key}/pages/${page.slug}`);
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 412) {
        key.current = newIdempotencyKey();
        setConflict(await pagesApi.bySlug(space.key, initial?.slug ?? ""));
      }
    },
  });

  const submit = () => {
    if (title.trim() !== "" && !save.isPending) save.mutate(baseRevision);
  };
  const change =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setter(value);
      setDirty(true);
    };

  const heading =
    mode === "create" ? t("pages.newPage") : t("editor.editing", { title: initial?.title ?? "" });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="space-y-4"
    >
      <PageHeader
        title={heading}
        breadcrumb={[
          { label: t("spaces.title"), to: "/spaces" },
          { label: space.name, to: `/spaces/${space.key}` },
          { label: heading },
        ]}
        secondaryActions={
          <Button
            onClick={() => {
              void navigate(-1);
            }}
          >
            {t("common.cancel")}
          </Button>
        }
        primaryAction={
          <Button
            type="submit"
            variant="primary"
            loading={save.isPending}
            disabled={title.trim() === ""}
          >
            {t("common.save")}
          </Button>
        }
      />
      <div className="grid gap-4 md:grid-cols-[2fr_3fr]">
        <TextField
          label={t("pages.pageTitle")}
          required
          maxLength={TITLE_MAX}
          value={title}
          autoFocus={mode === "create"}
          onChange={(event) => {
            change(setTitle)(event.target.value);
          }}
        />
        <TextField
          label={t("editor.message")}
          maxLength={MESSAGE_MAX}
          value={message}
          placeholder={t("editor.messagePlaceholder")}
          onChange={(event) => {
            change(setMessage)(event.target.value);
          }}
        />
      </div>
      <FormError
        error={save.error instanceof ApiError && save.error.status === 412 ? null : save.error}
      />
      <MarkdownEditor
        value={body}
        onChange={change(setBody)}
        onSave={submit}
        spaceKey={space.key}
        tree={tree}
        label={t("editor.body")}
        onAttach={
          initial === null
            ? undefined
            : async (file) => markdownFor(await attachmentsApi.upload(space.key, initial.id, file))
        }
      />
      <p className="text-xs text-text-muted">{t("editor.shortcut")}</p>
      <ConflictDialog
        latest={conflict}
        mine={{ title, body }}
        onClose={() => {
          setConflict(null);
        }}
        onKeepMine={() => {
          const latest = conflict;
          setConflict(null);
          if (latest !== null) {
            setBaseRevision(latest.revision_id);
            save.mutate(latest.revision_id);
          }
        }}
        onUseTheirs={() => {
          if (conflict !== null) {
            setTitle(conflict.title);
            setBody(conflict.body);
            setBaseRevision(conflict.revision_id);
          }
          setConflict(null);
        }}
      />
    </form>
  );
}
