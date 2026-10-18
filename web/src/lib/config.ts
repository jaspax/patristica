/** Base URL of the static library export (scripts/export_library.py). */
export const LIBRARY_URL = (process.env.NEXT_PUBLIC_LIBRARY_URL ?? "/library").replace(/\/$/, "");

/**
 * Base URL of the search API (api/, #141). In production the web app and the
 * API share an origin, and Caddy sends `/api/*` to FastAPI (infra/compose).
 */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/$/, "");
