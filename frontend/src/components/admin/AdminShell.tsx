"use client";
// Admin shell — Stitch screen 18 (desktop sidebar w-64 + 64px top bar). Auth/role gate unchanged.
import { createContext,useContext,useState } from "react";
import Link from "next/link";
import NextImage from "next/image";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ShieldCheck } from "lucide-react";
import s from "./admin.module.css";
import { DashThemeToggle, useDashTheme } from "@/components/ui/DashTheme";

/** Sidebar entries; `icon` is a Material Symbols name from the self-hosted subset. */
export const adminNavigation = [
 {label:"پیشخوان",href:"/admin",icon:"dashboard"}, {label:"کاتالوگ و کالاها",href:"/admin/catalog",icon:"inventory_2"},
 {label:"دسته‌بندی‌ها و برندها",href:"/admin/taxonomy",icon:"category"},
 {label:"کیفیت و انتشار کاتالوگ",href:"/admin/catalog-review",icon:"verified"}, {label:"تأمین‌کنندگان و Offerها",href:"/admin/suppliers",icon:"factory"},
 {label:"بررسی Offer و تاریخچه قیمت",href:"/admin/offers",icon:"price_change"},
 {label:"استعلام مشتریان",href:"/admin/inquiries",icon:"forum"}, {label:"حساب‌های سازمانی و فروشگاهی",href:"/admin/b2b",icon:"corporate_fare"}, {label:"تسویه همکاران فروش",href:"/admin/affiliates",icon:"handshake"}, {label:"سازمان‌ها و قراردادها",href:"/admin/organizations",icon:"history_edu"},
 {label:"خرید سازمانی و پرونده‌ها",href:"/admin/cases",icon:"receipt_long"}, {label:"مدیریت پک‌ها",href:"/admin/packs",icon:"card_giftcard"},
 {label:"لجستیک و مغایرت تحویل",href:"/admin/logistics",icon:"local_shipping"},
 {label:"مالی و تسویه",href:"/admin/settlements",icon:"account_balance_wallet"}, {label:"صورتحساب مودیان",href:"/admin/moadian",icon:"receipt"}, {label:"مرجوعی‌ها",href:"/admin/returns",icon:"assignment_returned"},
 {label:"محتوا و ویرایش بصری",href:"/admin/content",icon:"edit_square"}, {label:"کتابخانه رسانه",href:"/admin/media",icon:"image"},
 {label:"اعلان‌ها و پیام‌ها",href:"/admin/notifications",icon:"notifications"}, {label:"دسترسی‌ها و سیاست‌ها",href:"/admin/access",icon:"security"},
 {label:"مشتریان شخصی",href:"/admin/customers",icon:"group"}, {label:"سفارش‌های شخصی",href:"/admin/orders",icon:"shopping_bag"}, {label:"کاربران پلتفرم",href:"/admin/users",icon:"manage_accounts"},
 {label:"گزارش‌ها",href:"/admin/reports",icon:"analytics"}, {label:"تنظیمات",href:"/admin/settings",icon:"tune"}, {label:"تاریخچه تغییرات",href:"/admin/audit",icon:"history"},
];
const EditorState=createContext<(dirty:boolean)=>void>(()=>{});
export const useAdminEditorState=()=>useContext(EditorState);
const Icon=({name,className=""}:{name:string;className?:string})=><span aria-hidden="true" className={`material-symbols-outlined ${className}`}>{name}</span>;

export function AdminShell({children}:{children:React.ReactNode}) {
 const {user,loading,logout}=useAuth(),path=usePathname(); const [open,setOpen]=useState(false),[dirty,setDirty]=useState(false); const [theme,toggleTheme]=useDashTheme();
 const selected=adminNavigation.find(n=>n.href===path)??adminNavigation.find(n=>n.href!=="/admin"&&path.startsWith(n.href+"/"));
 if(loading)return <div className={s.gate} role="status">در حال بررسی حساب و دسترسی مدیریت…</div>;
 if(!user)return <div className={s.gate}><ShieldCheck size={36}/><h1>پیشخوان مدیریت 60Online</h1><p>برای ادامه با حساب مجاز مدیریت وارد شوید.</p><Link className={s.primary} href={"/login?next="+encodeURIComponent(path)}>ورود و ادامه</Link><Link href="/">بازگشت به فروشگاه</Link></div>;
 if(user.role!=="admin")return <div className={s.gate} role="alert"><ShieldCheck size={36}/><h1>دسترسی مدیریتی لازم است</h1><p>حساب فعلی مجوز ورود به پیشخوان کسب‌وکار را ندارد.</p><Link className={s.primary} href="/account">حساب کاربری من</Link></div>;
 if(path==="/admin/content/preview")return <>{children}</>;
 const leave=()=>!dirty||window.confirm("تغییرات ذخیره‌نشده کنار گذاشته شوند؟");
 const go=(e:React.MouseEvent)=>{if(!leave()){e.preventDefault();return;}setDirty(false);setOpen(false);};
 return <EditorState.Provider value={setDirty}><div className="min-h-dvh bg-st-background text-[14px] text-st-on-surface" dir="rtl" key={user.id}>
  {open&&<button className="fixed inset-0 z-40 bg-st-primary/40 lg:hidden" aria-label="بستن ناوبری" onClick={()=>setOpen(false)}/>}
  <aside id="admin-navigation" aria-label="ناوبری مدیریت" className={`text-base fixed right-0 top-0 z-50 flex h-full w-64 flex-col justify-between border-l border-st-surface-container bg-st-surface-container-lowest px-st-space-md py-st-space-lg transition-transform lg:translate-x-0 ${open?"translate-x-0":"translate-x-full"}`}>
   <div className="flex min-h-0 flex-col gap-st-space-lg">
    <div className="flex items-center justify-between gap-st-space-sm px-st-space-xs">
     <Link href="/admin" onClick={go} className="flex items-center gap-st-space-sm">
      <span className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg bg-st-surface-container-lowest"><NextImage src="/brand/60online-mark.png" width={36} height={34} alt="" unoptimized/></span>
      <span className="flex flex-col"><span className="font-bold text-st-primary">پیشخوان مدیریت ۶۰</span><span className="text-st-on-surface-variant">مدیریت کسب‌وکار</span></span>
     </Link>
     <button onClick={()=>setOpen(false)} aria-label="بستن منو" className="flex h-9 w-9 items-center justify-center rounded-xl bg-st-surface text-st-on-surface-variant lg:hidden"><Icon name="close" className="text-[20px]"/></button>
    </div>
    <nav className="-mx-st-space-xs flex min-h-0 flex-col gap-st-space-xs overflow-y-auto px-st-space-xs">
     {adminNavigation.map(({label,href,icon})=>{const on=selected?.href===href;return <Link href={href} key={href} onClick={go} aria-current={on?"page":undefined}
      className={on?"flex items-center gap-st-space-sm rounded-xl bg-st-primary-container px-st-space-md py-st-space-sm font-bold text-st-on-primary transition-colors"
       :"flex items-center gap-st-space-sm rounded-xl px-st-space-md py-st-space-sm text-st-on-surface-variant transition-colors hover:bg-st-surface-container hover:text-st-on-surface"}>
      <Icon name={icon} className="text-[20px]"/><span>{label}</span></Link>;})}
    </nav>
   </div>
   <div className="flex flex-col gap-st-space-md border-t border-st-surface-container-low pt-st-space-md">
    <Link href="/" onClick={e=>{if(!leave())e.preventDefault()}} className="flex items-center justify-between rounded-xl bg-st-surface p-st-space-sm text-st-on-surface-variant">
     <span>مشاهده فروشگاه</span><Icon name="open_in_new" className="text-[18px] text-st-secondary"/></Link>
    <div className="flex items-center justify-between px-st-space-xs">
     <div className="flex min-w-0 items-center gap-st-space-sm">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-st-primary"><Icon name="person" className="text-[18px] text-st-on-primary"/></span>
      <span className="flex min-w-0 flex-col"><span className="truncate font-semibold text-st-on-surface">{user.full_name||"مدیر"}</span><span className="text-st-outline">مدیر سامانه</span></span>
     </div>
     <button type="button" onClick={()=>{if(leave())logout()}} aria-label="خروج" title="خروج" className="flex items-center justify-center text-st-outline transition-colors hover:text-st-error"><Icon name="logout" className="text-[20px]"/></button>
    </div>
   </div>
  </aside>
  <div className="lg:pr-64">
   <header className="text-base sticky top-0 z-30 flex h-16 items-center justify-between gap-st-space-md border-b border-st-surface-container bg-st-surface-container-lowest px-st-space-md shadow-[0_1px_8px_rgba(0,0,0,0.02)] lg:px-st-space-xl">
    <div className="flex min-w-0 items-center gap-st-space-sm text-st-on-surface-variant">
     <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-st-surface lg:hidden" onClick={()=>setOpen(true)} aria-label="بازکردن منو" aria-expanded={open} aria-controls="admin-navigation"><Icon name="menu" className="text-[22px]"/></button>
     <span className="hidden text-st-outline sm:inline">پیشخوان مدیریت</span>
     <Icon name="chevron_left" className="hidden text-[16px] text-st-outline sm:inline"/>
     <span className="truncate font-bold text-st-primary">{selected?.label??"پرونده"}</span>
    </div>
    <div className="flex shrink-0 items-center gap-st-space-sm lg:gap-st-space-lg">
     <DashThemeToggle theme={theme} onToggle={toggleTheme}/>
     <Link href="/admin/notifications" onClick={go} aria-label="اعلان‌ها و پیام‌ها" className="flex h-10 w-10 items-center justify-center rounded-xl bg-st-surface text-st-on-surface-variant transition-colors hover:bg-st-surface-container"><Icon name="notifications" className="text-[20px]"/></Link>
     <Link href="/admin/catalog/new" onClick={go} className="hidden h-10 items-center gap-st-space-xs rounded-xl bg-st-primary-container px-st-space-md text-st-on-primary transition-colors hover:bg-st-secondary md:flex"><Icon name="add" className="text-[18px]"/><span>ثبت کالای جدید</span></Link>
    </div>
   </header>
   <main className="px-st-space-md py-st-space-lg lg:px-st-space-xl lg:py-st-space-xl">{children}</main>
  </div>
 </div></EditorState.Provider>;
}
