import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { PageHeader } from "../../../components/ui/PageHeader";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { spaceKeys, spacesApi, type Space, type Visibility } from "../api";
import { MembersSection } from "../components/MembersSection";
import { useSpaceContext } from "./SpaceLayout";

/** Space settings and members (space administrators and global administrators). */
export function SpaceSettingsPage() {
  const { space } = useSpaceContext();
  // Re-seed the form when the saved settings change.
  return (
    <SpaceSettings key={`${space.name}|${space.description}|${space.visibility}`} space={space} />
  );
}

function SpaceSettings({ space }: { space: Space }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [name, setName] = useState(space.name);
  const [description, setDescription] = useState(space.description);
  const [visibility, setVisibility] = useState<Visibility>(space.visibility);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const key = useRef(newIdempotencyKey());

  const update = useMutation({
    mutationFn: (body: Parameters<typeof spacesApi.update>[1]) =>
      spacesApi.update(space.key, body, key.current),
    onSuccess: async (updated) => {
      key.current = newIdempotencyKey();
      setConfirmArchive(false);
      queryClient.setQueryData(spaceKeys.space(space.key), updated);
      await queryClient.invalidateQueries({ queryKey: spaceKeys.all });
      toast(t("common.saved"));
    },
  });

  return (
    <div className="max-w-3xl space-y-10">
      <PageHeader
        title={t("spaces.settings")}
        breadcrumb={[
          { label: space.name, to: `/spaces/${space.key}` },
          { label: t("spaces.settings") },
        ]}
      />
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          update.mutate({ name, description, visibility });
        }}
      >
        <TextField
          label={t("spaces.name")}
          required
          maxLength={100}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <TextField
          label={t("admin.description")}
          maxLength={500}
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
        <SelectField
          label={t("spaces.visibilityLabel")}
          hint={t("spaces.visibilityHint")}
          value={visibility}
          onChange={(event) => {
            setVisibility(event.target.value as Visibility);
          }}
          options={[
            { value: "restricted", label: t("spaces.visibility.restricted") },
            { value: "internal", label: t("spaces.visibility.internal") },
          ]}
        />
        <FormError error={update.error} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" loading={update.isPending}>
            {t("common.save")}
          </Button>
          {space.archived ? (
            <Button
              onClick={() => {
                update.mutate({ archived: false });
              }}
            >
              {t("spaces.unarchive")}
            </Button>
          ) : (
            <Button
              variant="danger"
              onClick={() => {
                setConfirmArchive(true);
              }}
            >
              {t("spaces.archive")}
            </Button>
          )}
        </div>
      </form>
      <MembersSection spaceKey={space.key} />
      <ConfirmDialog
        open={confirmArchive}
        onOpenChange={setConfirmArchive}
        title={t("spaces.confirmArchive", { name: space.name })}
        description={t("spaces.confirmArchiveHelp")}
        confirmLabel={t("spaces.archive")}
        loading={update.isPending}
        onConfirm={() => {
          update.mutate({ archived: true });
        }}
      />
    </div>
  );
}
