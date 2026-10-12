import type { NextConfig } from "next";

import { legacyWorkRedirects } from "./src/lib/redirects";

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
  cacheComponents: true,
  partialPrefetching: true,
  allowedDevOrigins,
  // Old reader URLs of renamed works (src/lib/redirects.ts).
  redirects: async () => legacyWorkRedirects(),
};

export default nextConfig;
