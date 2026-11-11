"use client";
import dynamic from "next/dynamic";

export type MapBubble = { lat: number; lng: number; count: number; label: string; href?: string };
export type MapPoint = { lat: number; lng: number; label: string };
export type NetworkMapProps = {
  center?: [number, number]; zoom?: number; bubbles?: MapBubble[]; points?: MapPoint[]; height?: number; label?: string;
};

/** Client-only map (Leaflet touches window); pages render their lists independently of it. */
const NetworkMap = dynamic<NetworkMapProps>(() => import("./NetworkMapInner"), {
  ssr: false,
  loading: () => <div className="h-[420px] w-full animate-pulse rounded-2xl bg-neutral-100" aria-hidden />,
});

export default NetworkMap;
