import type { MetadataRoute } from "next";
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "شصت‌آنلاین | خرید برای خانه و سازمان", short_name: "شصت‌آنلاین", description: "اپ فروشگاه شصت‌آنلاین",
    id: "/", start_url: "/", scope: "/", lang: "fa", dir: "rtl", display: "standalone",
    background_color: "#F7F7F5", theme_color: "#FFFFFF", orientation: "portrait-primary",
    icons: [
      { src: "/brand/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/brand/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/brand/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/brand/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "سبد خرید", url: "/cart" }, { name: "سفارش‌های من", url: "/orders" }, { name: "دسته‌بندی‌ها", url: "/category" },
    ],
  };
}
