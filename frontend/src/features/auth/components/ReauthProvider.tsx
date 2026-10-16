import { startAuthentication } from "@simplewebauthn/browser";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/ui/Button";
import { Dialog } from "../../../components/ui/Dialog";
import { TextField } from "../../../components/ui/Field";
import { FormError } from "../../../components/ui/FormError";
import { setCsrfToken, setReauthHandler } from "../../../lib/api-client";
import { SESSION_KEY, useSession } from "../../../lib/auth";
import { authApi, type WebAuthnJson } from "../api";

/**
 * Step-up authentication. Any API call answered with `REAUTH_REQUIRED` opens this dialog; the
 * call is retried with the same idempotency key once the user confirmed their identity.
 */
export function ReauthProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const pending = useRef<((ok: boolean) => void) | null>(null);
  const methods = session.data?.mfa_methods ?? [];
  const viaSso = session.data?.user.auth_source === "oidc";

  useEffect(() => {
    setReauthHandler(
      () =>
        new Promise<boolean>((resolve) => {
          pending.current = resolve;
          setPassword("");
          setCode("");
          setOpen(true);
        }),
    );
    return () => {
      setReauthHandler(null);
    };
  }, []);

  const finish = (ok: boolean) => {
    setOpen(false);
    pending.current?.(ok);
    pending.current = null;
  };

  const confirm = useMutation({
    mutationFn: async (useKey: boolean) => {
      let credential: WebAuthnJson | undefined;
      if (useKey) {
        const options = await authApi.reauthWebauthnOptions();
        credential = (await startAuthentication({
          optionsJSON: options as never,
        })) as unknown as WebAuthnJson;
      }
      return authApi.reauth({
        password,
        totp_code: !useKey && code !== "" ? code : undefined,
        webauthn_credential: credential,
      });
    },
    onSuccess: async (step) => {
      setCsrfToken(step.csrf_token);
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
      finish(true);
    },
  });

  return (
    <>
      {children}
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) finish(false);
        }}
        title={t("reauth.title")}
        description={viaSso ? t("reauth.ssoDescription") : t("reauth.description")}
      >
        {viaSso ? (
          <div className="flex justify-end">
            {/* The identity provider confirms the identity; the action is repeated afterwards. */}
            <a
              href={`/api/v1/auth/oidc/reauth?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover"
            >
              {t("reauth.continueWithSso")}
            </a>
          </div>
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              confirm.mutate(false);
            }}
          >
            <TextField
              label={t("auth.password")}
              type="password"
              autoComplete="current-password"
              required
              autoFocus
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
            {methods.includes("totp") && (
              <TextField
                label={t("auth.authenticatorCode")}
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
              />
            )}
            <FormError error={confirm.error} />
            <div className="flex flex-wrap justify-end gap-2">
              {methods.includes("webauthn") && (
                <Button
                  disabled={password === ""}
                  onClick={() => {
                    confirm.mutate(true);
                  }}
                >
                  {t("auth.useSecurityKey")}
                </Button>
              )}
              <Button
                type="submit"
                variant="primary"
                loading={confirm.isPending}
                disabled={password === ""}
              >
                {t("reauth.confirm")}
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}
