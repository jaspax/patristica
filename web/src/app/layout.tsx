import type { Metadata, Viewport } from "next";

import SiteFooter from "@/components/SiteFooter";
import SiteHeader from "@/components/SiteHeader";
import { SITE_URL } from "@/lib/seo";

import { fontVariables } from "./fonts";
import "./globals.css";

const description =
  "Scripture and the writings of the Church Fathers from the first thousand years of Christianity, " +
  "searchable by meaning or exact phrase in Greek, Latin, Hebrew, Syriac, Coptic, Ge‘ez, Armenian, Gothic and Church Slavonic.";

export const metadata: Metadata = {
  // Resolves the Open Graph image to an absolute URL.
  metadataBase: new URL(SITE_URL),
  title: { default: "Patristica", template: "%s · Patristica" },
  description,
  openGraph: {
    siteName: "Patristica",
    title: "Patristica",
    description,
    images: [{ url: "/images/hero-1536.jpg", width: 1536, height: 614, alt: "" }],
  },
};

// The browser chrome takes the header's colour (globals.css --surface).
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f0e8" },
    { media: "(prefers-color-scheme: dark)", color: "#1f1d17" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={fontVariables}>
      <body>
        <SiteHeader />
        {/* The skip link's target (SiteHeader). */}
        <div id="content" tabIndex={-1}>
          {children}
        </div>
        <SiteFooter />
      </body>
    </html>
  );
}
