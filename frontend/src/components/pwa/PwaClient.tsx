"use client";

// Registers /sw.js (production only) and shows an «نصب اپ» button only when the browser reports the app installable.
import { useEffect, useState } from "react";
import { Download } from "lucide-react";

type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

export function PwaClient() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);

  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    }
    const onPrompt = (e: Event) => { e.preventDefault(); setPrompt(e as InstallPrompt); };
    const onInstalled = () => setPrompt(null);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => { window.removeEventListener("beforeinstallprompt", onPrompt); window.removeEventListener("appinstalled", onInstalled); };
  }, []);

  if (!prompt) return null;
  const install = async () => {
    await prompt.prompt();
    await prompt.userChoice.catch(() => null);
    setPrompt(null); // a prompt can be used once
  };
  return (
    <button type="button" onClick={install}
      className="fixed bottom-20 left-4 z-40 flex min-h-11 items-center gap-2 rounded-full bg-neutral-900 px-4 py-2 text-sm font-bold text-white shadow-lg md:bottom-6">
      <Download className="h-4 w-4" aria-hidden="true" />نصب اپ
    </button>
  );
}
