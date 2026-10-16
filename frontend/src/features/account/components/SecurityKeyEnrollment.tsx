import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { accountApi, type EnrollmentResponse } from "../api";

/** Registers a security key or passkey (WebAuthn). */
export function SecurityKeyEnrollment({
  onEnrolled,
}: {
  onEnrolled: (result: EnrollmentResponse) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const register = useMutation({
    mutationFn: async () => {
      const options = await accountApi.securityKeyOptions();
      const credential = await startRegistration({ optionsJSON: options as never });
      return accountApi.registerSecurityKey(
        name.trim(),
        credential as unknown as Record<string, unknown>,
      );
    },
    onSuccess: (result) => {
      setName("");
      onEnrolled(result);
    },
  });

  if (!browserSupportsWebAuthn()) {
    return <p className="text-text-muted">{t("account.webauthnUnsupported")}</p>;
  }
  return (
    <form
      className="flex max-w-md flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        register.mutate();
      }}
    >
      <TextField
        label={t("account.keyName")}
        maxLength={64}
        required
        value={name}
        onChange={(event) => {
          setName(event.target.value);
        }}
        placeholder={t("account.keyNamePlaceholder")}
      />
      <FormError error={register.error} />
      <Button
        type="submit"
        loading={register.isPending}
        disabled={name.trim() === ""}
        icon={<KeyRound aria-hidden className="size-4" />}
        className="self-start"
      >
        {t("account.addSecurityKey")}
      </Button>
    </form>
  );
}
