// Vambi's own chrome: no 60Online header/footer — an independent identity inside the same ecosystem.
export function VambiMark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} aria-label="وامبی">
      <svg viewBox="0 0 40 40" className="h-9 w-9" aria-hidden="true">
        <rect width="40" height="40" rx="12" fill="#4C2BD6" />
        <path d="M11 12l9 17 9-17" fill="none" stroke="#FFC23D" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="20" cy="31.5" r="2.2" fill="#fff" />
      </svg>
      <span className="text-2xl font-black tracking-tight text-[#24135F]">وامبی</span>
    </span>
  );
}

export function VambiShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[#F6F4FF]">
      <header className="border-b border-[#E4DEFF] bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <a href="/vambi"><VambiMark /></a>
          <a href="/login" className="rounded-full bg-[#24135F] px-4 py-2 text-sm font-bold text-white">ورود مشتریان</a>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-[#E4DEFF] py-6 text-center text-xs text-neutral-500">
        وامبی فقط فروشنده‌های معتبرِ عضو اکوسیستم شصت آنلاین را مقایسه می‌کند.
      </footer>
    </div>
  );
}
