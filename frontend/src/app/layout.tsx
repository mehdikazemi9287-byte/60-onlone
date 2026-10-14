import type { Metadata, Viewport } from "next";
import { Vazirmatn } from "next/font/google";
import "./globals.css";
import { PublicChrome } from "@/components/layout/PublicChrome";
import { Toaster } from "@/components/ui/Toaster";
import { AuthProvider } from "@/lib/auth-context";

const vazirmatn = Vazirmatn({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-vazirmatn",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://60online.ir"),
  alternates: { canonical: "/" },
  title: {
    default: "60Online | بازار جامع خرید ایران",
    template: "%s | 60Online",
  },
  description:
    "60Online بازار جامع ایرانی برای کالای دیجیتال، لوازم خانگی، سوپرمارکت، اداری و تحریر، سلامت و زیبایی و خرید سازمانی — با پک‌ساز هوشمند و باشگاه 60Club.",
  keywords: ["خرید اینترنتی", "کالای دیجیتال", "لوازم خانگی", "سوپرمارکت", "خرید سازمانی", "60Online"],
  authors: [{ name: "60Online" }],
  manifest: "/manifest.webmanifest",
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
  themeColor: "#102A43",
  colorScheme: "light",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl" className={vazirmatn.variable}>
      <body className="min-h-screen flex flex-col bg-neutral-50">
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
        </AuthProvider>
      </body>
    </html>
  );
}
