import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { SelectField, TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { useToast } from "../../../components/ui/Toast";
import { newIdempotencyKey } from "../../../lib/api-client";
import { formatDateTime } from "../../../lib/format";
import { useUnsavedChangesWarning } from "../../../lib/unsaved-changes";
import { operationsApi, type SettingsResponse, type TestableSection } from "../api";
import {
  SECTION_FIELDS,
  CONNECTION_TEST,
  TESTABLE,
  toBody,
  toForm,
  type FieldSpec,
  type FormValues,
} from "../settings-fields";

const AREA =
  "w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs disabled:opacity-60";

function AreaField({
  label,
  hint,
  value,
  disabled,
  rows,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  disabled: boolean;
  rows: number;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
        value={value}
        disabled={disabled}
        spellCheck={false}
        maxLength={65536}
        aria-describedby={hint !== undefined ? `${id}-hint` : undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className={AREA}
      />
      {hint !== undefined && (
        <p id={`${id}-hint`} className="text-xs text-text-muted">
          {hint}
        </p>
      )}
    </div>
  );
}

/** One settings section: save, reset to defaults and (where it applies) send a test message. */
export function SettingsSectionForm({ data }: { data: SettingsResponse }) {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const section = data.section;
  const initial = useMemo(() => toForm(section, data.values), [section, data.values]);
  const [form, setForm] = useState<FormValues>(initial);
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [confirmReset, setConfirmReset] = useState(false);
  const key = useRef(newIdempotencyKey());
  const readOnly = data.managed_by_environment;
  const managed = useMemo(() => new Set(data.managed_fields), [data.managed_fields]);
  const locked = (name: string) => readOnly || managed.has(name);
  const connectionTest = CONNECTION_TEST.includes(section);
  const dirty =
    cleared.size > 0 || Object.keys(initial).some((name) => initial[name] !== form[name]);
  const release = useUnsavedChangesWarning(dirty && !readOnly);

  const onSaved = (saved: SettingsResponse) => {
    key.current = newIdempotencyKey();
    release();
    queryClient.setQueryData(["admin", "settings", section], saved);
  };
  const save = useMutation({
    mutationFn: () =>
      operationsApi.saveSettings(section, toBody(section, form, cleared, managed), key.current),
    onSuccess: (saved) => {
      onSaved(saved);
      toast(t("common.saved"));
    },
  });
  const reset = useMutation({
    mutationFn: () => operationsApi.resetSettings(section),
    onSuccess: (saved) => {
      setConfirmReset(false);
      onSaved(saved);
      toast(t("settings.resetDone"));
    },
  });
  const test = useMutation({
    mutationFn: () => operationsApi.testSettings(section as TestableSection),
  });

  const label = (field: FieldSpec) =>
    managed.has(field.name)
      ? `${t(`settings.fields.${section}.${field.name}`)} (${t("settings.fromEnvironment")})`
      : t(`settings.fields.${section}.${field.name}`);
  const hint = (field: FieldSpec) => {
    const hintKey = `settings.hints.${section}.${field.name}`;
    return i18n.exists(hintKey) ? t(hintKey) : undefined;
  };
  const set = (name: string, value: string | boolean) => {
    setForm((current) => ({ ...current, [name]: value }));
  };

  const renderField = (field: FieldSpec) => {
    const value = form[field.name];
    if (field.kind === "boolean") {
      return (
        <label key={field.name} className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={value === true}
            disabled={locked(field.name)}
            onChange={(event) => {
              set(field.name, event.target.checked);
            }}
            className="mt-0.5 size-4"
          />
          <span>
            <span className="font-medium">{label(field)}</span>
            {hint(field) !== undefined && (
              <span className="block text-xs text-text-muted">{hint(field)}</span>
            )}
          </span>
        </label>
      );
    }
    if (field.kind === "pem" || field.kind === "list" || field.kind === "mapping") {
      return (
        <AreaField
          key={field.name}
          label={label(field)}
          hint={hint(field)}
          rows={field.kind === "pem" ? 6 : 4}
          value={String(value)}
          disabled={locked(field.name)}
          onChange={(next) => {
            set(field.name, next);
          }}
        />
      );
    }
    if (field.kind === "select") {
      return (
        <SelectField
          key={field.name}
          label={label(field)}
          value={String(value)}
          disabled={locked(field.name)}
          onChange={(event) => {
            set(field.name, event.target.value);
          }}
          options={(field.options ?? []).map((option) => {
            const optionKey = `settings.options.${section}.${field.name}.${option}`;
            return { value: option, label: i18n.exists(optionKey) ? t(optionKey) : option };
          })}
        />
      );
    }
    if (field.kind === "secret") {
      const stored = data.values[field.name];
      const isCleared = cleared.has(field.name);
      return (
        <div key={field.name} className="space-y-1">
          <TextField
            label={label(field)}
            type="password"
            autoComplete="new-password"
            value={String(value)}
            maxLength={field.maxLength}
            disabled={locked(field.name) || isCleared}
            placeholder={
              typeof stored === "string" ? t("settings.secretUnchanged", { mask: stored }) : ""
            }
            hint={hint(field) ?? t("settings.secretHint")}
            onChange={(event) => {
              set(field.name, event.target.value);
            }}
          />
          {typeof stored === "string" && !locked(field.name) && (
            <button
              type="button"
              className="text-xs text-danger underline"
              onClick={() => {
                setCleared((current) => {
                  const next = new Set(current);
                  if (isCleared) next.delete(field.name);
                  else next.add(field.name);
                  return next;
                });
              }}
            >
              {isCleared ? t("settings.keepSecret") : t("settings.clearSecret")}
            </button>
          )}
        </div>
      );
    }
    return (
      <TextField
        key={field.name}
        label={label(field)}
        hint={hint(field)}
        type={field.kind === "number" ? "number" : "text"}
        min={field.min}
        max={field.max}
        step={field.step}
        maxLength={field.maxLength}
        value={String(value)}
        disabled={locked(field.name)}
        onChange={(event) => {
          set(field.name, event.target.value);
        }}
      />
    );
  };

  return (
    <form
      className="max-w-2xl space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">{t(`settings.sections.${section}`)}</h2>
        <p className="text-text-muted">{t(`settings.descriptions.${section}`)}</p>
        {readOnly && <Badge tone="primary">{t("settings.managedByEnvironment")}</Badge>}
        {data.updated_at !== null && (
          <p className="text-xs text-text-muted">
            {t("settings.updated", {
              date: formatDateTime(data.updated_at),
              user: data.updated_by ?? "—",
            })}
          </p>
        )}
      </div>
      {SECTION_FIELDS[section].map(renderField)}
      {section === "security" && (
        <p className="text-text-muted">
          {t("settings.trustedProxies", { count: Number(data.info.trusted_proxy_count ?? 0) })}
        </p>
      )}
      <FormError error={save.error ?? reset.error ?? test.error} />
      {test.data !== undefined && (
        <p
          role="status"
          className={`rounded-md border px-3 py-2 ${test.data.ok ? "border-success/40 text-success" : "border-danger/40 text-danger"}`}
        >
          {test.data.ok
            ? connectionTest
              ? test.data.message
              : t("settings.testOk")
            : t("settings.testFailed", { message: test.data.message })}
        </p>
      )}
      {!readOnly && (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {TESTABLE.includes(section) && (
            <Button
              loading={test.isPending}
              disabled={dirty}
              title={dirty ? t("settings.saveBeforeTest") : undefined}
              onClick={() => {
                test.mutate();
              }}
            >
              {connectionTest ? t("settings.testConnection") : t("settings.sendTest")}
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={() => {
              setConfirmReset(true);
            }}
          >
            {t("settings.reset")}
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title={t("settings.confirmReset", { section: t(`settings.sections.${section}`) })}
        description={t("settings.confirmResetHelp")}
        confirmLabel={t("settings.reset")}
        loading={reset.isPending}
        onConfirm={() => {
          reset.mutate();
        }}
      />
    </form>
  );
}
