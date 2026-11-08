import { Nunito } from "next/font/google";

// Vambi's own chrome: no 60Online header/footer — an independent identity inside the same ecosystem.
// Logo vectors: Figma file "Vambi — Logo" (component Vambi/Mark), exported to /public/vambi/mark.svg.
const nunito = Nunito({ subsets: ["latin"], weight: ["900"], display: "swap" });

export function VambiMark({ size = 44 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2" aria-label="وامبی">
      <img src="/vambi/mark.svg" alt="" width={Math.round(size * 1.43)} height={size} style={{ height: size, width: "auto" }} />
      <span className="flex flex-col leading-none">
        <span className={`${nunito.className} text-[22px] font-black tracking-tight text-[#102B7A]`} dir="ltr">
          VAMB<span className="relative">ı<span className="absolute -top-[3px] left-1/2 h-[7px] w-[7px] -translate-x-1/2 rounded-full bg-[#FF8A00]" /></span>
        </span>
        <span className="text-xs font-bold text-[#102B7A]">وامبی</span>
      </span>
    </span>
  );
}

export function VambiHeroLogo() {
  return (
    <div className="flex flex-col items-center">
      <img src="/vambi/mark.svg" alt="" width={300} height={209} className="h-auto w-[230px] md:w-[300px]" />
      <span className={`${nunito.className} mt-1 text-6xl font-black tracking-tight text-[#102B7A] md:text-7xl`} dir="ltr">
        VAMB<span className="relative">ı<span className="absolute -top-[8px] left-1/2 h-[18px] w-[18px] -translate-x-1/2 rounded-full bg-gradient-to-b from-[#FFC233] to-[#FF7A00] md:h-[22px] md:w-[22px]" /></span>
      </span>
      <span className="mt-1 flex items-center gap-4 text-2xl font-bold text-[#102B7A]">
        <span className="h-[3px] w-12 rounded bg-[#FF8A00]" aria-hidden="true" />وامبی<span className="h-[3px] w-12 rounded bg-[#FF8A00]" aria-hidden="true" />
      </span>
    </div>
  );
}

export function VambiShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[#F5F7FD]">
      <header className="border-b border-[#DCE3F7] bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2">
          <a href="/vambi"><VambiMark /></a>
          <a href="/login" className="rounded-full bg-[#102B7A] px-4 py-2 text-sm font-bold text-white">ورود مشتریان</a>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-[#DCE3F7] py-6 text-center text-xs text-neutral-600">
        وامبی فقط فروشنده‌های معتبرِ عضو اکوسیستم شصت آنلاین را مقایسه می‌کند.
      </footer>
    </div>
  );
}
