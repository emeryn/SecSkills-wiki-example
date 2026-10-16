import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import "./lib/i18n";

let prefersDark = false;

export function setPrefersDark(value: boolean): void {
  prefersDark = value;
}

// jsdom does not implement modal dialogs.
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.removeAttribute("open");
  this.dispatchEvent(new Event("close"));
};

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  prefersDark = false;
  window.matchMedia = (query: string) =>
    ({
      matches: query === "(prefers-color-scheme: dark)" && prefersDark,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList;
});

afterEach(() => {
  cleanup();
});
