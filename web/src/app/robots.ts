import type { MetadataRoute } from "next";

import { ROBOTS } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return ROBOTS;
}
