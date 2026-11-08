"use client";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Building2, MapPin, FileText, Package, Plus } from "lucide-react";
import { RequestProductPicker, type RequestSelection } from "@/components/catalog/RequestProductPicker";
import { applyOp, emptyDraft, loadDraft, newItem, saveDraft } from "@/lib/procurement/draft";
import { apiRequest } from "@/lib/api";
import { toPersianNum } from "@/lib/utils";

const collections=[{name:"آریا",supplier:"آریا",q:"",detail:"نوشت‌افزار و لوازم آموزشی"},{name:"پویا پروتئین",supplier:"پویا پروتئین",q:"",detail:"گوشت، مرغ و فرآورده‌های پروتئینی"},{name:"کاله",supplier:"",q:"کاله",detail:"لبنیات و محصولات غذایی"}];
export default function BusinessCatalog(){const {user}=useAuth();return <BusinessCatalogBody key={user?.id??"guest"}/>;}
function BusinessCatalogBody(){
 const params=useSearchParams(),router=useRouter();
 const [selected,setSelected]=useState<RequestSelection[]>([]),[counts,setCounts]=useState<Record<string,number>>({}),[error,setError]=useState("");
 useEffect(()=>{let active=true; for(const c of collections){const qs=new URLSearchParams({supplier:c.supplier,q:c.q,page_size:"1"});apiRequest<{total:number}>("/catalog/selection?"+qs).then(r=>active&&setCounts(n=>({...n,[c.name]:r.total}))).catch(()=>{});}return()=>{active=false};},[]);
 function continueRequest(){
  if(!selected.length)return;
  if(selected.some(x=>!Number.isInteger(x.quantity)||x.quantity<1||x.quantity>100000)){setError("تعداد هر کالا باید عدد صحیح بین ۱ و ۱۰۰٬۰۰۰ باشد.");return;}
  let draft=loadDraft()??emptyDraft();
  for(const {product:p,quantity} of selected){const existing=draft.items.find(i=>i.masterProductId===p.id);draft=existing?applyOp(draft,{type:"updateItem",id:existing.id,patch:{quantity:existing.quantity+quantity}}):applyOp(draft,{type:"addItem",item:newItem(p.name,quantity,{masterProductId:p.id,sku:p.supplier_codes[0]??null,unit:p.unit??"",catalog:"matched"})});}
  if(draft.items.some(i=>!Number.isSafeInteger(i.quantity)||i.quantity<1||i.quantity>100000)){setError("جمع تعداد با پیش‌نویس موجود بیش از حد مجاز است؛ ابتدا پیش‌نویس را بررسی کنید.");return;}
  if(draft.items.length>50){setError("درخواست حداکثر ۵۰ قلم دارد؛ ابتدا پیش‌نویس موجود را بررسی کنید.");return;}
  if(!saveDraft(draft)){setError("ذخیره‌سازی مرورگر در دسترس نیست؛ برای حفظ اقلام، ابتدا آن را فعال کنید.");return;}
  router.push("/organization/compose");
 }
 return <main className="mx-auto max-w-[1280px] space-y-8 px-4 py-6 md:px-8 md:py-10" dir="rtl">
  <nav className="flex flex-wrap gap-4 text-xs text-[#52616a]"><Link href="/">60Online</Link><span>/</span><Link href="/org">خرید سازمانی</Link><span>/</span><span>کاتالوگ تأمین</span></nav>
  <section className="rounded-[24px] bg-[#edf2eb] p-6 md:p-9"><span className="flex items-center gap-2 text-xs font-bold text-[#a93d1a]"><Building2 size={16}/>کاتالوگ درخواست سازمانی</span><h1 className="mt-3 text-2xl font-black leading-relaxed text-[#0a2735] md:text-3xl">کالاهای چند مجموعه را یک‌جا انتخاب کنید</h1><p className="mt-3 max-w-3xl text-sm leading-8 text-[#43565d]">کالای موردنیاز را از کاتالوگ انتخاب کنید؛ سپس مقدار هر قلم، شهرها و نشانی مجموعه‌های دریافت‌کننده را در یک درخواست مشخص کنید. قیمت، موجودی و امکان ارسال پس از بررسی تأمین اعلام می‌شود.</p><div className="mt-5 flex flex-wrap gap-4 text-xs font-bold text-[#0a2735]"><span className="flex items-center gap-2"><Package size={16}/>انتخاب از چند مجموعه</span><span className="flex items-center gap-2"><MapPin size={16}/>مقصد و سهم هر شعبه</span><span className="flex items-center gap-2"><FileText size={16}/>ثبت و پیگیری درخواست</span></div></section>
  <section aria-label="مجموعه‌های کاتالوگ" className="grid gap-3 sm:grid-cols-3">{collections.map(c=><Link key={c.name} href={"/business/catalog?"+new URLSearchParams({supplier:c.supplier,q:c.q})} className="flex min-h-28 items-center gap-4 rounded-2xl border border-[#dce5df] bg-white p-5 hover:border-[#004e72]"><span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#faf9f6] text-lg font-black text-[#0a2735]">{c.name[0]}</span><div className="min-w-0 flex-1"><b className="text-base text-[#0a2735]">{c.name}</b><p className="mt-1 text-xs leading-6 text-[#52616a]">{c.detail}</p>{counts[c.name]!==undefined&&<p className="mt-1 text-xs font-bold text-[#004e72]">{toPersianNum(counts[c.name])} قلم قابل درخواست</p>}</div><ArrowLeft size={16} className="shrink-0 text-[#52616a]"/></Link>)}</section>
  <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-black text-[#0a2735]">انتخاب اقلام درخواست</h2><Link href="/business/catalog" className="min-h-11 py-3 text-sm font-bold text-[#004e72]">همه مجموعه‌ها</Link></div>
  <RequestProductPicker key={params.toString()} initialSupplier={params.get("supplier")??""} initialQuery={params.get("q")??""} value={selected} onChange={setSelected}/>
  {error&&<p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-800">{error}</p>}
  <div className="sticky bottom-20 z-20 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#dce5df] bg-white p-4 shadow-lg md:bottom-5"><div><b className="text-sm text-[#0a2735]">{toPersianNum(selected.length)} قلم انتخاب‌شده</b><p className="mt-1 text-xs leading-6 text-[#52616a]">اقلام به پیش‌نویس موجود اضافه می‌شوند؛ مقصدها در مرحله بعد.</p></div><button type="button" onClick={continueRequest} disabled={!selected.length} className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-[#C4461C] px-5 text-sm font-bold text-white disabled:opacity-40">ادامه و تعیین شهرها <ArrowLeft size={16}/></button></div>
 </main>;
}
