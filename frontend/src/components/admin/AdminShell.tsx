"use client";
import { createContext,useContext,useState } from "react";
import Link from "next/link";
import NextImage from "next/image";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Menu, X, ArrowUpLeft, LayoutDashboard, Package, Truck, Users, Building2, ClipboardList, Boxes, Wallet, FileText, Image, Bell, ShieldCheck, BarChart3, Settings2, History } from "lucide-react";
import s from "./admin.module.css";
export const adminNavigation = [
 {label:"پیشخوان",href:"/admin",icon:LayoutDashboard}, {label:"کاتالوگ و کالاها",href:"/admin/catalog",icon:Package},
 {label:"دسته‌بندی‌ها و برندها",href:"/admin/taxonomy",icon:Boxes},
 {label:"کیفیت و انتشار کاتالوگ",href:"/admin/catalog-review",icon:ShieldCheck}, {label:"تأمین‌کنندگان و Offerها",href:"/admin/suppliers",icon:Truck},
 {label:"بررسی Offer و تاریخچه قیمت",href:"/admin/offers",icon:Truck},
 {label:"استعلام مشتریان",href:"/admin/inquiries",icon:Users}, {label:"حساب‌های سازمانی و فروشگاهی",href:"/admin/b2b",icon:Building2}, {label:"تسویه همکاران فروش",href:"/admin/affiliates",icon:Users}, {label:"سازمان‌ها و قراردادها",href:"/admin/organizations",icon:Building2}, {label:"شبکهٔ فروشگاه‌ها",href:"/admin/network",icon:Building2},
 {label:"خرید سازمانی و پرونده‌ها",href:"/admin/cases",icon:ClipboardList}, {label:"مدیریت پک‌ها",href:"/admin/packs",icon:Boxes},
 {label:"مالی و تسویه",href:"/admin/settlements",icon:Wallet}, {label:"مرجوعی‌ها",href:"/admin/returns",icon:Package},
 {label:"محتوا و ویرایش بصری",href:"/admin/content",icon:FileText}, {label:"کتابخانه رسانه",href:"/admin/media",icon:Image},
 {label:"اعلان‌ها و پیام‌ها",href:"/admin/notifications",icon:Bell}, {label:"دسترسی‌ها و سیاست‌ها",href:"/admin/access",icon:ShieldCheck},
 {label:"مشتریان شخصی",href:"/admin/customers",icon:Users}, {label:"سفارش‌های شخصی",href:"/admin/orders",icon:Package}, {label:"کاربران پلتفرم",href:"/admin/users",icon:Users},
 {label:"گزارش‌ها",href:"/admin/reports",icon:BarChart3}, {label:"وامبی: آمادگی و سنجش",href:"/admin/vambi",icon:BarChart3}, {label:"تنظیمات",href:"/admin/settings",icon:Settings2}, {label:"تاریخچه تغییرات",href:"/admin/audit",icon:History},
];
const EditorState=createContext<(dirty:boolean)=>void>(()=>{});
export const useAdminEditorState=()=>useContext(EditorState);
export function AdminShell({children}:{children:React.ReactNode}) {
 const {user,loading,logout}=useAuth(),path=usePathname(); const [open,setOpen]=useState(false),[dirty,setDirty]=useState(false);
 const selected=adminNavigation.find(n=>n.href===path)??adminNavigation.find(n=>n.href!=="/admin"&&path.startsWith(n.href+"/"));
 if(loading)return <div className={s.gate} role="status">در حال بررسی حساب و دسترسی مدیریت…</div>;
 if(!user)return <div className={s.gate}><ShieldCheck size={36}/><h1>پیشخوان مدیریت 60Online</h1><p>برای ادامه با حساب مجاز مدیریت وارد شوید.</p><Link className={s.primary} href={"/login?next="+encodeURIComponent(path)}>ورود و ادامه</Link><Link href="/">بازگشت به فروشگاه</Link></div>;
 if(user.role!=="admin")return <div className={s.gate} role="alert"><ShieldCheck size={36}/><h1>دسترسی مدیریتی لازم است</h1><p>حساب فعلی مجوز ورود به پیشخوان کسب‌وکار را ندارد.</p><Link className={s.primary} href="/account">حساب کاربری من</Link></div>;
 if(path==="/admin/content/preview")return <>{children}</>;
 const leave=()=>!dirty||window.confirm("تغییرات ذخیره‌نشده کنار گذاشته شوند؟");
 return <EditorState.Provider value={setDirty}><div className={s.shell} dir="rtl" key={user.id}>
  {open&&<button className={s.scrim} aria-label="بستن ناوبری" onClick={()=>setOpen(false)}/>}
  <aside className={`${s.sidebar} ${open?s.open:""}`} aria-label="ناوبری مدیریت" id="admin-navigation"><div className={s.brand}><Link href="/admin" className={s.brandLink} onClick={e=>{if(!leave()){e.preventDefault();return;}setDirty(false);setOpen(false)}}><NextImage src="/brand/60online-logo.jpeg" width={52} height={52} alt="شصت آنلاین" unoptimized/><span><span className={s.brandName}>شصت آنلاین</span><span>مدیریت کسب‌وکار</span></span></Link><button onClick={()=>setOpen(false)} aria-label="بستن منو" className={s.mobile}><X size={20}/></button></div>
   <nav>{adminNavigation.map(({label,href,icon:Icon})=><Link href={href} key={href} onClick={e=>{if(!leave()){e.preventDefault();return;}setDirty(false);setOpen(false)}} aria-current={selected?.href===href?"page":undefined} className={selected?.href===href?s.active:""}><Icon size={18}/><span>{label}</span></Link>)}</nav>
   <Link href="/" onClick={e=>{if(!leave())e.preventDefault()}} className={s.store}>مشاهده فروشگاه<ArrowUpLeft size={16}/></Link>
  </aside>
  <div className={s.body}><header className={s.topbar}><div><button className={s.mobile} onClick={()=>setOpen(true)} aria-label="بازکردن منو" aria-expanded={open} aria-controls="admin-navigation"><Menu size={22}/></button><span>پیشخوان / <b>{selected?.label??"پرونده"}</b></span></div><div><span className={s.identity}>{user.full_name||"مدیر"}</span><button onClick={()=>{if(leave())logout()}}>خروج</button></div></header><div className={s.content}>{children}</div></div>
 </div></EditorState.Provider>;
}
