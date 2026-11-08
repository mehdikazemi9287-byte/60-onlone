"use client";

import { useState } from "react";
import Image from "next/image";
import { ImageOff } from "lucide-react";
import { cn } from "@/lib/utils";

/** Presents the original catalog asset without altering packaging or geometry. */
export function ProductMedia({ src, name, priority = false, className }: {
  src?: string; name: string; priority?: boolean; className?: string;
}) {
  const [failedSource, setFailedSource] = useState<string>();
  const valid = !!src && !src.includes("picsum.photos") && failedSource !== src;
  return <div className={cn("product-media", (!src || src.includes("picsum.photos")) && "product-media-missing", className)}>
    {valid && src.startsWith("/images/catalog/") ? <Image src={src} alt={name} fill
      sizes={priority ? "(max-width: 1023px) 100vw, 640px" : "(max-width: 767px) 50vw, (max-width: 1023px) 50vw, 400px"}
      quality={85} priority={priority} fetchPriority={priority ? "high" : "auto"} onError={() => setFailedSource(src)} /> : valid ? <img src={src} alt={name} width={640} height={640}
      loading={priority ? "eager" : "lazy"} decoding="async"
      fetchPriority={priority ? "high" : "auto"}
      onError={() => setFailedSource(src)} /> :
      <div className="product-media-empty" role="img" aria-label={`تصویر ${name} موجود نیست`}>
        <ImageOff aria-hidden="true" strokeWidth={1.2} />
        <span>تصویر موجود نیست</span>
      </div>}
  </div>;
}
