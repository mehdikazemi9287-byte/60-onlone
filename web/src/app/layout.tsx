import type { Metadata, Viewport } from "next";
import "@fontsource-variable/vazirmatn";
import "@fontsource/nunito/900.css";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { VambiShell } from "@/components/VambiShell";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://vambi.ir"),
  title: { default: "وامبی | جستجو و مقایسهٔ قیمت فروشندگان معتبر", template: "%s | وامبی" },
  description: "وامبی: کشف کن، مقایسه کن، هوشمندانه انتخاب کن. یک کالا، همهٔ فروشنده‌های معتبر کنار هم.",
  applicationName: "وامبی",
  icons: { icon: "/vambi/icon.svg", apple: "/vambi/icon.svg" },
};
export const viewport: Viewport = { themeColor: "#102B7A", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <AuthProvider>
          <VambiShell>{children}</VambiShell>
        </AuthProvider>
      </body>
    </html>
  );
}
