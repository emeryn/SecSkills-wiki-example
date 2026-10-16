import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { useSession } from "../lib/auth";

const WARN_BEFORE_MS = 2 * 60 * 1000;

/** Offers to stay signed in two minutes before the idle timeout; reading the session extends it. */
export function SessionExpiryWarning() {
  const { t } = useTranslation();
  const session = useSession();
  const [open, setOpen] = useState(false);
  const expiresAt = session.data?.idle_expires_at;

  useEffect(() => {
    if (expiresAt === undefined) return;
    const delay = new Date(expiresAt).getTime() - Date.now() - WARN_BEFORE_MS;
    const timer = window.setTimeout(
      () => {
        // Other API calls may already have extended the session: check before warning.
        void session.refetch().then((result) => {
          const remaining = result.data
            ? new Date(result.data.idle_expires_at).getTime() - Date.now()
            : 0;
          if (remaining <= WARN_BEFORE_MS) setOpen(true);
        });
      },
      Math.max(delay, 0),
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [expiresAt, session]);

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t("session.expiringTitle")}
      description={t("session.expiringHelp")}
    >
      <div className="flex justify-end">
        <Button
          variant="primary"
          onClick={() => {
            setOpen(false);
            void session.refetch();
          }}
        >
          {t("session.staySignedIn")}
        </Button>
      </div>
    </Dialog>
  );
}
