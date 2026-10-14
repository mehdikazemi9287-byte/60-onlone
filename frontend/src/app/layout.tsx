import type { Metadata, Viewport } from "next";
import { Vazirmatn } from "next/font/google";
import "./globals.css";
import "./premium.css";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { Toaster } from "@/components/ui/Toaster";
import { AuthProvider } from "@/lib/auth-context";

const vazirmatn = Vazirmatn({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-vazirmatn",
  display: "swap",
});

export const metadata: Metadata = {
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
        <AuthProvider>
          <Header />
          <main className="flex-1" style={{ minBlockSize: "var(--commerce-content-min-height, 100svh)" }}>{children}</main>
          <Footer />
          <Toaster />
        </AuthProvider>
      </body>
    </html>
  );
}
