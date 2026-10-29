import type { MetadataRoute } from "next";
import { connection } from "next/server";

import { sitemapEntries } from "@/lib/seo";
import { serverLibrary } from "@/lib/serverLibrary";

// Every work and author page (#406), from the published library. Built per
// request, not at build time: the build has no library, and a publish adds works.
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  await connection();
  const { index, authors } = await serverLibrary();
  return sitemapEntries(index, authors);
}
