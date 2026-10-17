import type { NextConfig } from "next";

import { legacyAuthorRedirects, legacyWorkRedirects } from "./src/lib/redirects";

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
  // Old reader URLs of renamed works, and pages of renamed authors (src/lib/redirects.ts).
  redirects: async () => [...legacyWorkRedirects(), ...legacyAuthorRedirects()],
};

export default nextConfig;
