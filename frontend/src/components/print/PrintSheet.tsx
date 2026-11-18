"use client";
// A4 print sheet rendered as a direct child of <body> (portal). globals.css hides everything else in print,
// always prints on white paper (even in dark mode) and keeps the sheet on its own pages.
// The browser's «Save as PDF» keeps Persian text shaping correct, which JS PDF libraries do not.
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { faDate } from "@/lib/utils";

export function PrintSheet({ children, onDone }: { children: ReactNode; onDone: () => void }) {
  useEffect(() => {
    window.addEventListener("afterprint", onDone);
    const t = setTimeout(() => window.print(), 150);
    return () => { clearTimeout(t); window.removeEventListener("afterprint", onDone); };
  }, [onDone]);
  return createPortal(<div className="print-doc" dir="rtl" aria-hidden="true">{children}</div>, document.body);
}

export function PrintHead({ title, number, date }: { title: string; number?: string; date?: string }) {
  return (
    <header className="cp-head">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/brand/60online-mark.png" alt="" />
      <div style={{ flex: 1 }}><h1>{title}</h1><p>شصت‌آنلاین · تاریخ: {date ?? faDate(new Date().toISOString().slice(0, 10))}</p></div>
      {number && <div className="cp-no"><span>شماره</span><b dir="ltr">{number}</b></div>}
    </header>
  );
}

export function SignBoxes({ labels, images }: { labels: string[]; images?: Record<number, ReactNode> }) {
  return (
    <div className="cp-sign" style={{ gridTemplateColumns: `repeat(${labels.length}, 1fr)` }}>
      {labels.map((l, i) => <div key={l}><b>{l}</b><span>نام، امضا و تاریخ</span>{images?.[i]}</div>)}
    </div>
  );
}

// Code128 code-set B, verified against python-barcode's table (106 symbols + stop).
const P = ["212222","222122","222221","121223","121322","131222","122213","122312","132212","221213","221312","231212","112232","122132","122231","113222","123122","123221","223211","221132","221231","213212","223112","312131","311222","321122","321221","312212","322112","322211","212123","212321","232121","111323","131123","131321","112313","132113","132311","211313","231113","231311","112133","112331","132131","113123","113321","133121","313121","211331","231131","213113","213311","213131","311123","311321","331121","312113","312311","332111","314111","221411","431111","111224","111422","121124","121421","141122","141221","112214","112412","122114","122411","142112","142211","241211","221114","413111","241112","134111","111242","121142","121241","114212","124112","124211","411212","421112","421211","212141","214121","412121","111143","111341","131141","114113","114311","411113","411311","113141","114131","311141","411131","211412","211214","211232","2331112"];

/** SVG Code128-B barcode; returns null for characters outside code set B. */
export function Code128({ data, height = 44 }: { data: string; height?: number }) {
  if (!data || [...data].some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) > 126)) return null;
  const vals = [...data].map((c) => c.charCodeAt(0) - 32);
  const check = (104 + vals.reduce((s, v, i) => s + (i + 1) * v, 0)) % 103;
  const seq = [104, ...vals, check, 106];
  const bars: { x: number; w: number }[] = [];
  let x = 10;
  for (const v of seq) [...P[v]].forEach((d, i) => { const w = +d; if (i % 2 === 0) bars.push({ x, w }); x += w; });
  const width = x + 10;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width={width * 1.6} height={height} role="img" aria-label={`بارکد ${data}`} shapeRendering="crispEdges">
      <rect width={width} height={height} fill="#fff" />
      {bars.map((b, i) => <rect key={i} x={b.x} y={0} width={b.w} height={height} fill="#000" />)}
    </svg>
  );
}
