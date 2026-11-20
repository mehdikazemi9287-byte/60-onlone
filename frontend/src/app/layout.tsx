import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { PublicChrome } from "@/components/layout/PublicChrome";
import { Toaster } from "@/components/ui/Toaster";
import { AuthProvider } from "@/lib/auth-context";
import { PwaClient } from "@/components/pwa/PwaClient";
import { RefCapture } from "@/components/affiliate/RefCapture";
import { ChunkReloadGuard } from "@/components/system/ChunkReloadGuard";

// Self-hosted (SIL OFL, rastikerdar/vazirmatn v33.0.3): Google Fonts is unreliable from Iran and blocks builds offline.
const vazirmatn = localFont({
  src: "./fonts/Vazirmatn-wght.woff2",
  weight: "100 900",
  variable: "--font-vazirmatn",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://60online.ir"),
  // No site-wide canonical here: each indexable page declares its own, so pages never inherit "/".
  title: {
    default: "60Online | بازار جامع خرید ایران",
    template: "%s | 60Online",
  },
  description:
    "60Online بازار جامع ایرانی برای کالای دیجیتال، لوازم خانگی، سوپرمارکت، اداری و تحریر، سلامت و زیبایی و خرید سازمانی — با پک‌ساز هوشمند و باشگاه 60Club.",
  keywords: ["خرید اینترنتی", "کالای دیجیتال", "لوازم خانگی", "سوپرمارکت", "خرید سازمانی", "60Online"],
  authors: [{ name: "60Online" }],
  manifest: "/manifest.webmanifest",
  icons: { icon: [{ url: "/brand/icon-192.png", sizes: "192x192" }], apple: "/brand/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "شصت‌آنلاین", statusBarStyle: "default" },
  applicationName: "60Online",
  openGraph: {
    title: "60Online | بازار جامع خرید ایران",
    description: "کالای دیجیتال، لوازم خانگی، سوپرمارکت و خرید سازمانی در یک پلتفرم هوشمند",
    locale: "fa_IR",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#FFFFFF",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable} suppressHydrationWarning>
      <head>
        {/* Apply the saved light/dark theme before first paint (no flash). */}
        <script dangerouslySetInnerHTML={{ __html: `try{var t=localStorage.getItem("60online_theme");if(t==="dark"){document.documentElement.dataset.theme="dark";document.documentElement.style.colorScheme="dark"}}catch(e){}` }} />
      </head>
      <body className="min-h-screen flex flex-col bg-canvas">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@graph": [
                { "@type": "Organization", "@id": "https://60online.ir/#org", name: "شصت‌آنلاین", alternateName: "60Online", url: "https://60online.ir" },
                { "@type": "WebSite", "@id": "https://60online.ir/#website", url: "https://60online.ir", name: "شصت‌آنلاین", inLanguage: "fa-IR", publisher: { "@id": "https://60online.ir/#org" }, potentialAction: { "@type": "SearchAction", target: "https://60online.ir/search?q={search_term_string}", "query-input": "required name=search_term_string" } }
              ]
            }).replace(/</g, "\\u003c"),
          }}
        />

        <AuthProvider>
          <PublicChrome>{children}</PublicChrome>
          <Toaster />
          <PwaClient />
          <RefCapture />
        </AuthProvider>
        <ChunkReloadGuard />
      </body>
    </html>
  );
}
