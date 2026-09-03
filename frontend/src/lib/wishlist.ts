"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "60online_wishlist";
const CHANGE_EVENT = "60online:wishlist-changed";

function readSlugs(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(value)
      ? Array.from(new Set(value.filter((item): item is string => typeof item === "string" && item.length > 0)))
      : [];
  } catch {
    return [];
  }
}

function writeSlugs(slugs: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(slugs));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useWishlist() {
  const [slugs, setSlugs] = useState<string[]>([]);

  useEffect(() => {
    const refresh = () => setSlugs(readSlugs());
    refresh();
    window.addEventListener(CHANGE_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(CHANGE_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const toggle = useCallback((slug: string) => {
    const current = readSlugs();
    writeSlugs(current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug]);
  }, []);

  const remove = useCallback((slug: string) => {
    writeSlugs(readSlugs().filter((item) => item !== slug));
  }, []);

  return { slugs, toggle, remove, has: (slug: string) => slugs.includes(slug) };
}
