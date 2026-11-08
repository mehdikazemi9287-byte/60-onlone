"use client";
// Card-quality gate for real catalog photos. A card shows a photo only if it is large enough,
// roughly square (not a wide banner or tall spec sheet) and sits on a light background
// (dark-cornered images are lifestyle banners or close-ups, not the product).
import { useEffect, useState } from "react";

const verdicts = new Map<string, Promise<boolean>>();

function lightCorners(im: HTMLImageElement): boolean {
  try {
    const c = document.createElement("canvas"); c.width = c.height = 24;
    const g = c.getContext("2d"); if (!g) return true;
    g.drawImage(im, 0, 0, 24, 24);
    const px = [[1, 1], [22, 1], [1, 22], [22, 22]].map(([x, y]) => g.getImageData(x, y, 1, 1).data);
    const lum = px.reduce((a, d) => a + (d[3] < 20 ? 255 : 0.2126 * d[0] + 0.7152 * d[1] + 0.0722 * d[2]), 0) / px.length;
    return lum >= 200;
  } catch { return true; }
}

export function checkImage(url: string): Promise<boolean> {
  let v = verdicts.get(url);
  if (!v) {
    v = new Promise<boolean>((resolve) => {
      const im = new window.Image();
      const timer = setTimeout(() => resolve(false), 8000);
      im.onload = () => {
        clearTimeout(timer);
        const w = im.naturalWidth, h = im.naturalHeight;
        resolve(Math.min(w, h) >= 250 && w / h >= 0.72 && w / h <= 1.4 && lightCorners(im));
      };
      im.onerror = () => { clearTimeout(timer); resolve(false); };
      im.src = url;
    });
    verdicts.set(url, v);
  }
  return v;
}

/** Returns the subset of `urls` that pass the card-quality gate (null while checking). */
export function useGoodImages(urls: (string | null | undefined)[]): Set<string> | null {
  const list = [...new Set(urls.filter((u): u is string => !!u && !u.includes("picsum.photos")))];
  const key = list.join("|");
  const [good, setGood] = useState<Set<string> | null>(null);
  useEffect(() => {
    let off = false;
    setGood(null);
    Promise.all(list.map((u) => checkImage(u).then((ok) => (ok ? u : null)))).then((r) => {
      if (!off) setGood(new Set(r.filter((u): u is string => !!u)));
    });
    return () => { off = true; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return good;
}
