// Side-effect import first: configures zod before any schema module is evaluated.
import "./lib/zod-config";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { Providers } from "./app/providers";
import { routes } from "./app/router";
import "./lib/i18n";
import { applyTheme, readThemePreference } from "./lib/theme";
import "./styles/global.css";

// Applied before the first render to avoid a flash of the wrong theme (no inline script: CSP).
applyTheme(readThemePreference());

const root = document.getElementById("root");
if (root === null) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={createBrowserRouter(routes)} />
    </Providers>
  </StrictMode>,
);
