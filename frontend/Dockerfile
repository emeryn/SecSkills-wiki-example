# syntax=docker/dockerfile:1
# Build context: repository root. Final stage: unprivileged Nginx with the shell and apk removed.
ARG NODE_IMAGE=node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6

FROM ${NODE_IMAGE} AS deps
WORKDIR /src
ARG NPM_REGISTRY
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
 && npm ci --no-audit
COPY frontend/ ./
# Embedded help, imported at build time from ../docs/help relative to the frontend.
COPY docs/help /docs/help

FROM deps AS audit
RUN npm audit --audit-level=high

FROM deps AS test
CMD ["sh", "-c", "npm run lint && npm run typecheck && npm run format:check && npm test"]

FROM deps AS build
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
USER root
COPY --from=build /src/dist /usr/share/nginx/html
COPY --chmod=0644 deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=0644 deploy/nginx/proxy_backend.conf /etc/nginx/proxy_backend.conf
COPY --chmod=0644 deploy/nginx/proxy_stream.conf /etc/nginx/proxy_stream.conf
# Last RUN: removes the package manager, entrypoint scripts and every busybox applet (incl. sh).
RUN rm -rf /docker-entrypoint.sh /docker-entrypoint.d /sbin/apk /etc/apk /lib/apk /var/cache/apk \
 && for f in /bin/* /sbin/* /usr/bin/* /usr/sbin/*; do \
      case "$(/bin/busybox readlink "$f")" in *busybox) /bin/busybox rm -f "$f" ;; esac; \
    done \
 && /bin/busybox rm -f /bin/busybox
USER 101:101
EXPOSE 8443
ENTRYPOINT ["nginx", "-g", "daemon off;"]
