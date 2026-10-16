import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Smartphone, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { ErrorState } from "../../../components/ui/ErrorState";
import { FormError } from "../../../components/ui/FormError";
import { Skeleton } from "../../../components/ui/Skeleton";
import { useToast } from "../../../components/ui/Toast";
import { useApplyStep } from "../../../lib/auth";
import { formatDateTime } from "../../../lib/format";
import { accountApi, type EnrollmentResponse, type SecurityKey } from "../api";
import { RecoveryCodes } from "./RecoveryCodes";
import { SecurityKeyEnrollment } from "./SecurityKeyEnrollment";
import { TotpEnrollment } from "./TotpEnrollment";

const MFA_KEY = ["account", "mfa"] as const;

export function SecuritySection() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const applyStep = useApplyStep();
  const status = useQuery({ queryKey: MFA_KEY, queryFn: accountApi.mfaStatus });
  const [codes, setCodes] = useState<string[] | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<"totp" | SecurityKey | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: MFA_KEY });

  const enrolled = async (result: EnrollmentResponse) => {
    await applyStep(result);
    if (result.recovery_codes.length > 0) setCodes(result.recovery_codes);
    toast(t("account.factorAdded"));
    await refresh();
  };
  const remove = useMutation({
    mutationFn: (target: "totp" | SecurityKey) =>
      target === "totp" ? accountApi.removeTotp() : accountApi.removeSecurityKey(target.id),
    onSuccess: async () => {
      setConfirmRemove(null);
      toast(t("account.factorRemoved"));
      await refresh();
    },
  });
  const regenerate = useMutation({
    mutationFn: accountApi.regenerateRecoveryCodes,
    onSuccess: (result) => {
      setCodes(result.codes);
      void refresh();
    },
  });

  if (status.isPending) return <Skeleton className="h-32 w-full max-w-md" />;
  if (status.isError)
    return <ErrorState error={status.error} onRetry={() => void status.refetch()} />;
  const mfa = status.data;

  return (
    <div className="max-w-2xl space-y-8">
      {codes !== null && <RecoveryCodes codes={codes} />}
      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <Smartphone aria-hidden className="size-4" />
          {t("account.authenticatorApp")}
          <Badge tone={mfa.totp ? "success" : "neutral"}>
            {mfa.totp ? t("account.enabled") : t("account.notSetUp")}
          </Badge>
        </h2>
        {mfa.totp ? (
          <Button
            variant="ghost"
            icon={<Trash2 aria-hidden className="size-4" />}
            onClick={() => {
              setConfirmRemove("totp");
            }}
          >
            {t("account.removeAuthenticator")}
          </Button>
        ) : (
          <TotpEnrollment onEnrolled={(result) => void enrolled(result)} />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <KeyRound aria-hidden className="size-4" />
          {t("account.securityKeys")}
        </h2>
        {mfa.security_keys.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {mfa.security_keys.map((key) => (
              <li key={key.id} className="flex items-center justify-between gap-4 px-3 py-2">
                <div>
                  <p className="font-medium">{key.name}</p>
                  <p className="text-xs text-text-muted">
                    {t("account.keyAdded", { date: formatDateTime(key.created_at) })}
                    {key.last_used_at !== null &&
                      ` · ${t("account.keyUsed", { date: formatDateTime(key.last_used_at) })}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  aria-label={t("account.removeKey", { name: key.name })}
                  icon={<Trash2 aria-hidden className="size-4" />}
                  onClick={() => {
                    setConfirmRemove(key);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
        <SecurityKeyEnrollment onEnrolled={(result) => void enrolled(result)} />
      </section>

      {(mfa.totp || mfa.security_keys.length > 0) && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold">{t("account.recoveryCodesTitle")}</h2>
          <p className="text-text-muted">
            {t("account.recoveryCodesLeft", { count: mfa.recovery_codes_left })}
          </p>
          <FormError error={regenerate.error} />
          <Button
            loading={regenerate.isPending}
            onClick={() => {
              regenerate.mutate();
            }}
          >
            {t("account.regenerateCodes")}
          </Button>
        </section>
      )}

      <ConfirmDialog
        open={confirmRemove !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmRemove(null);
        }}
        title={
          confirmRemove === "totp"
            ? t("account.confirmRemoveAuthenticator")
            : t("account.confirmRemoveKey", { name: confirmRemove?.name ?? "" })
        }
        description={t("account.confirmRemoveFactorHelp")}
        confirmLabel={t("common.remove")}
        loading={remove.isPending}
        onConfirm={() => {
          if (confirmRemove !== null) remove.mutate(confirmRemove);
        }}
      />
      <FormError error={remove.error} />
    </div>
  );
}
