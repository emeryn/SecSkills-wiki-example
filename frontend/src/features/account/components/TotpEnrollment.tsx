import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { accountApi, type EnrollmentResponse } from "../api";

/** Authenticator app setup: scan the QR code (or type the key), then confirm with a code. */
export function TotpEnrollment({
  onEnrolled,
}: {
  onEnrolled: (result: EnrollmentResponse) => void;
}) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const setup = useMutation({ mutationFn: accountApi.startTotp });
  const confirm = useMutation({ mutationFn: accountApi.confirmTotp, onSuccess: onEnrolled });

  if (setup.data === undefined) {
    return (
      <div className="space-y-2">
        <Button
          variant="primary"
          loading={setup.isPending}
          onClick={() => {
            setup.mutate();
          }}
        >
          {t("account.setUpAuthenticator")}
        </Button>
        <FormError error={setup.error} />
      </div>
    );
  }
  return (
    <form
      className="max-w-md space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        confirm.mutate(code.trim());
      }}
    >
      <p>{t("account.scanQr")}</p>
      <img
        src={setup.data.qr_png_data_uri}
        alt={t("account.qrAlt")}
        className="size-48 rounded-md bg-white p-2"
      />
      <p className="text-text-muted">
        {t("account.manualKey")}{" "}
        <code className="font-mono break-all text-text">{setup.data.secret}</code>
      </p>
      <TextField
        label={t("auth.authenticatorCode")}
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        value={code}
        onChange={(event) => {
          setCode(event.target.value);
        }}
      />
      <FormError error={confirm.error} />
      <Button
        type="submit"
        variant="primary"
        loading={confirm.isPending}
        disabled={code.trim().length < 6}
      >
        {t("account.confirmAuthenticator")}
      </Button>
    </form>
  );
}
