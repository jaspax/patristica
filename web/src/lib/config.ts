/** Base URL of the static library export (scripts/export_library.py). */
export const LIBRARY_URL = (process.env.NEXT_PUBLIC_LIBRARY_URL ?? "/library").replace(/\/$/, "");
