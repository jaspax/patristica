# The web app as served on the droplet (infra/compose, #132). Build context is
# web/. `output: "standalone"` in next.config.ts makes `next build` emit a
# self-contained server.js, so the final image needs no `npm ci` of its own.
#
# NEXT_PUBLIC_* values are inlined into the client bundle by `next build`, so
# they are build arguments: changing NEXT_PUBLIC_LIBRARY_URL means rebuilding
# the image, not restarting the container.
FROM node:22.23.3-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1

# Dependencies only, from the lock file, so source changes don't reinstall them.
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM base AS build
WORKDIR /app
ARG NEXT_PUBLIC_LIBRARY_URL
RUN test -n "$NEXT_PUBLIC_LIBRARY_URL" || { echo "build arg NEXT_PUBLIC_LIBRARY_URL is required" >&2; exit 1; }
ENV NEXT_PUBLIC_LIBRARY_URL=$NEXT_PUBLIC_LIBRARY_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS run
WORKDIR /app
# HOSTNAME: Docker sets it to the container id, and server.js would bind to that.
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# The standalone server serves .next/static and public/ only from beside
# itself. .next stays writable for the server's runtime cache.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node

EXPOSE 3000
CMD ["node", "server.js"]
