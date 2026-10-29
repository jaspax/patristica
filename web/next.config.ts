import type { NextConfig } from "next";

import { HTML_LIMITED_BOT_UA_RE } from "next/dist/shared/lib/router/utils/html-bots";

import { legacyAuthorRedirects, legacyPageRedirects, legacyWorkRedirects } from "./src/lib/redirects";

// `next dev` serves its client assets and hot-reload socket only to localhost
// unless the origin is listed here. Allow Tailscale addresses (100.x.y.z) and
// MagicDNS names (*.ts.net); add others as a comma-separated list in
// ALLOWED_DEV_ORIGINS. Only affects the dev server.
const allowedDevOrigins = [
  "100.*.*.*",
  "**.ts.net",
  ...(process.env.ALLOWED_DEV_ORIGINS?.split(",").map((s) => s.trim()).filter(Boolean) ?? []),
];

const nextConfig: NextConfig = {
  // A self-contained server (.next/standalone/server.js) for the Docker image
  // that runs on the droplet (web/Dockerfile, infra/compose, #132).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  allowedDevOrigins,
  // Crawlers that get a blocking render, with the metadata in <head> instead of
  // streamed into <body>: Next's list plus Googlebot, since Google honours a
  // canonical link only in <head> (#406).
  htmlLimitedBots: new RegExp(`Googlebot|${HTML_LIMITED_BOT_UA_RE.source}`, "i"),
  // Moved pages, old reader URLs of renamed works, and pages of renamed authors (src/lib/redirects.ts).
  redirects: async () => [...legacyPageRedirects(), ...legacyWorkRedirects(), ...legacyAuthorRedirects()],
  // Development only: `API_PROXY_URL=http://localhost:8000 npm run dev` sends /api/* to a
  // local API, as Caddy does in production (prefix stripped). Unset in the Docker build.
  rewrites: async () =>
    process.env.API_PROXY_URL
      ? [{ source: "/api/:path*", destination: `${process.env.API_PROXY_URL.replace(/\/$/, "")}/:path*` }]
      : [],
};

export default nextConfig;
