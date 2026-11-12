"use client";
/**
 * Leaflet + OpenStreetMap map for the retail network pages. Loaded only on the client via NetworkMap (ssr:false).
 * Uses circle markers only (no marker image assets). If tiles or the library fail, the parent page still lists data.
 */
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { MapBubble, MapPoint, NetworkMapProps } from "./NetworkMap";

const IRAN_CENTER: [number, number] = [32.4, 53.7];

function esc(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export default function NetworkMapInner({ center = IRAN_CENTER, zoom = 5, bubbles = [], points = [], height = 420, label }: NetworkMapProps) {
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const key = JSON.stringify({ center, zoom, bubbles, points });

  useEffect(() => {
    let disposed = false;
    let map: import("leaflet").Map | null = null;
    (async () => {
      try {
        const L = (await import("leaflet")).default;
        if (disposed || !ref.current) return;
        map = L.map(ref.current, { center, zoom, scrollWheelZoom: false, attributionControl: true });
        const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        });
        tiles.addTo(map);
        const max = Math.max(1, ...bubbles.map((b) => b.count));
        bubbles.forEach((b: MapBubble) => {
          const r = b.count > 0 ? 8 + Math.sqrt(b.count / max) * 22 : 6;
          const c = L.circleMarker([b.lat, b.lng], {
            radius: r, weight: 1.5, color: b.count > 0 ? "#102B7A" : "#9ca3af",
            fillColor: b.count > 0 ? "#1748C9" : "#ffffff", fillOpacity: b.count > 0 ? 0.45 : 0.15,
          }).addTo(map!);
          c.bindTooltip(`<div dir="rtl">${esc(b.label)}</div>`, { direction: "top" });
          if (b.href) c.on("click", () => router.push(b.href!));
        });
        points.forEach((p: MapPoint) => {
          L.circleMarker([p.lat, p.lng], { radius: 5, weight: 1, color: "#7c2d12", fillColor: "#ea580c", fillOpacity: 0.9 })
            .addTo(map!).bindPopup(`<div dir="rtl">${esc(p.label)}</div>`);
        });
        if (points.length > 1 && bubbles.length === 0) {
          map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number])), { padding: [30, 30], maxZoom: 13 });
        }
      } catch {
        if (!disposed) setFailed(true);
      }
    })();
    return () => { disposed = true; map?.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (failed) return <p className="rounded-xl bg-neutral-50 p-4 text-sm text-neutral-500">نقشه بارگذاری نشد؛ فهرست زیر کامل است.</p>;
  return <div ref={ref} dir="ltr" role="region" aria-label={label ?? "نقشه"} className="z-0 w-full overflow-hidden rounded-2xl border border-neutral-200 bg-neutral-50" style={{ height }} />;
}
