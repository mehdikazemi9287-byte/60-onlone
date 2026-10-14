"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Building2, Boxes, MapPin, FileText, Check, Sparkles } from "lucide-react";

export default function BusinessHero({content}:{content?:{title?:string;body?:string;link?:string;button_label?:string;image_url?:string}}={}) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  function compose(e: FormEvent) {
    e.preventDefault();
    router.push(`/organization/compose${prompt.trim() ? `?q=${encodeURIComponent(prompt.trim())}&tab=assistant` : ""}`);
  }
  return <section className="relative overflow-hidden rounded-[24px] border border-[#dce5df] bg-[#edf2eb]" aria-labelledby="business-title">
    <div className="grid items-center gap-8 p-6 md:grid-cols-[1.15fr_1fr] md:p-10 lg:gap-12 lg:p-12">
      <div>
        <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#c7d8cd] bg-white/75 px-3 py-2 text-xs font-bold text-[#0a2735]"><Building2 size={15}/>60Online Business · تأمین برای سازمان شما</p>
        <h1 id="business-title" className="text-[30px] font-black leading-[1.65] text-[#0a2735] md:text-[42px]">{content?.title||<>چند تأمین‌کننده.<br/><span className="text-[#a93d1a]">چند مقصد. یک درخواست.</span></>}</h1>
        <p className="mt-4 max-w-xl text-sm leading-8 text-[#43565d] md:text-base">{content?.body||"از تدارکات روزمره و مواد غذایی تا نوشت‌افزار و پک کارکنان؛ اقلام را انتخاب کنید، مقدار و شهر هر مجموعه را مشخص کنید و برای بررسی تأمین و قیمت روز درخواست بفرستید."}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href={content?.link||"/business/catalog"} className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#C4461C] px-6 text-sm font-bold text-white hover:bg-[#a93d1a]">{content?.button_label||"انتخاب کالا و ساخت درخواست"} <ArrowLeft size={17}/></Link>
          <Link href="/organization/compose" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-[#b9c8c0] bg-white px-5 text-sm font-bold text-[#0a2735]">نیازتان را بنویسید <FileText size={17}/></Link>
        </div>
        <form onSubmit={compose} className="mt-6 flex items-center gap-2 rounded-xl border border-[#d1ded5] bg-white p-2">
          <Sparkles size={18} className="mr-1 shrink-0 text-[#a93d1a]"/>
          <input aria-label="شرح نیاز سازمان" value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="مثلاً پک پذیرایی برای شعبه‌های چند شهر…" className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none focus:ring-2 focus:ring-[#004e72]"/>
          <button className="min-h-10 rounded-lg bg-[#0a2735] px-3 text-xs font-bold text-white">شروع درخواست</button>
        </form>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-[#52616a]"><span className="inline-flex items-center gap-1"><Check size={14}/>قیمت و امکان ارسال پس از استعلام</span><Link href="/search" className="inline-flex min-h-10 items-center gap-1 font-bold text-[#0a2735]">خرید شخصی <ArrowLeft size={14}/></Link></div>
      </div>
      <div className="relative mx-auto w-full max-w-[460px]" aria-label="مسیر درخواست سازمانی">
        {content?.image_url ? <img src={content.image_url} alt={content.title||"تصویر تأییدشده خدمات سازمانی"} className="relative aspect-square w-full rounded-[24px] object-contain"/> : <>
        <div className="absolute -inset-4 rounded-full bg-[#d5e4d9]/60 blur-3xl" aria-hidden="true"/>
        <div className="relative rounded-[24px] border border-white/90 bg-white/80 p-5 shadow-[0_16px_50px_-24px_rgba(10,39,53,0.35)] md:p-7">
          <div className="mb-6 flex items-center justify-between"><span className="text-sm font-black text-[#0a2735]">از نیاز تا درخواست تأمین</span><span className="rounded-full bg-[#e5eee7] px-3 py-1.5 text-[10px] font-bold text-[#3e6550]">مسیر خرید سازمانی</span></div>
          <div className="grid grid-cols-3 gap-2">{["کالای مصرفی", "مواد غذایی", "نوشت‌افزار"].map((label,i)=><div key={label} className="flex aspect-square flex-col items-center justify-center gap-3 rounded-2xl border border-[#e4e9e3] bg-[#faf9f6]"><Boxes size={28} strokeWidth={1.4} className={i===1?"text-[#a93d1a]":"text-[#004e72]"}/><span className="text-[11px] font-bold text-[#0a2735]">{label}</span></div>)}</div>
          <div className="mx-auto h-8 w-px bg-[#bccfc2]" aria-hidden="true"/>
          <div className="flex items-center gap-3 rounded-2xl bg-[#0a2735] p-4 text-white"><div className="rounded-xl bg-white/10 p-3"><FileText size={23}/></div><div><b className="block text-sm">یک فهرست خرید مشترک</b><span className="mt-1 block text-xs text-white/70">انتخاب اقلام، مقدار و موعد موردنیاز</span></div></div>
          <div className="mx-auto h-8 w-px bg-[#bccfc2]" aria-hidden="true"/>
          <div className="grid grid-cols-3 gap-2">{["دفتر مرکزی", "شعبه", "مجموعه"].map(label=><div key={label} className="flex flex-col items-center gap-2 rounded-xl border border-[#d8e4dc] bg-[#edf2eb] p-3"><MapPin size={20} className="text-[#004e72]"/><b className="text-[11px] text-[#0a2735]">{label}</b><span className="text-[10px] text-[#52616a]">شهر و سهم جداگانه</span></div>)}</div>
          <p className="mt-5 text-center text-[11px] leading-6 text-[#52616a]">ثبت درخواست، قبل از تأیید قیمت و شرایط، سفارش قطعی نیست.</p>
        </div>
        </>}
      </div>
    </div>
  </section>;
}
