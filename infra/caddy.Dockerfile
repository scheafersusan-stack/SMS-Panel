# syntax=docker/dockerfile:1.7
# Caddy with the static panel web baked in. Build context: repository root.
FROM node:22-alpine AS web
WORKDIR /web
COPY apps/panel-web/package.json apps/panel-web/package-lock.json ./
RUN npm ci
COPY apps/panel-web/ ./
# `npm run build` also runs the postbuild step that writes .csp/csp.caddy (inline-script hashes).
RUN npm run build

FROM caddy:2.10-alpine
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /web/dist /srv
COPY --from=web /web/.csp /etc/caddy/csp
