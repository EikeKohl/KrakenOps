# syntax=docker/dockerfile:1
#
# Multi-stage build for the KrakenOps dashboard.
#
# Stage 1 (deps) — install pnpm deps. Cached on package.json + pnpm-lock.
# Stage 2 (builder) — produce the Next.js standalone output.
# Stage 3 (runtime) — minimal node image carrying only the standalone bundle.

# Pin pnpm to the version package.json declares under "packageManager".
# Bumping node base images can drop bundled corepack (node 25 did), so we
# install pnpm directly via npm rather than relying on `corepack enable`.
ARG PNPM_VERSION=9.12.0


FROM node:26-alpine AS deps

ARG PNPM_VERSION
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@${PNPM_VERSION} && pnpm install --frozen-lockfile


FROM node:26-alpine AS builder

ARG PNPM_VERSION
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* env vars are baked at BUILD time (Next.js inlines them).
# Default points the browser at the host's exposed backend port; users can
# override via build-arg if they're running with a different topology.
ARG NEXT_PUBLIC_KRAKENOPS_API=http://localhost:8787
ENV NEXT_PUBLIC_KRAKENOPS_API=${NEXT_PUBLIC_KRAKENOPS_API}

RUN npm install -g pnpm@${PNPM_VERSION} && pnpm build


FROM node:26-alpine AS runtime

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Run as a non-root user. The standalone output is self-contained so this
# just needs to own /app.
RUN addgroup -S app && adduser -S app -G app && chown app:app /app
USER app

# `output: "standalone"` (next.config.ts) emits a server.js + minimal
# node_modules. .next/static and public/ are copied alongside.
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
