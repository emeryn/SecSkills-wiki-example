import { useCallback, useEffect, useRef } from "react";
import { useBlocker } from "react-router";
import i18n from "./i18n";

/**
 * Warns before leaving a form with unsaved changes (in-app navigation and tab close).
 * Returns `release()`, to call right before navigating away after a successful save.
 */
export function useUnsavedChangesWarning(dirty: boolean): () => void {
  const active = useRef(dirty);
  useEffect(() => {
    active.current = dirty;
  }, [dirty]);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      active.current && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm(i18n.t("common.unsavedChanges"))) blocker.proceed();
    else blocker.reset();
  }, [blocker]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [dirty]);

  return useCallback(() => {
    active.current = false;
  }, []);
}
