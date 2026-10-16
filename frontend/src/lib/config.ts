/** Build-time configuration. The bundle never contains secrets or environment-specific URLs. */
export const config = {
  appName: "Wiki",
  version: __APP_VERSION__,
  apiBasePath: "/api/v1",
} as const;
