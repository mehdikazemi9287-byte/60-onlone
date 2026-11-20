"use client";
import { createContext,useContext,useEffect,useState } from "react";
import Link from "next/link";
import NextImage from "next/image";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { mfa as mfaApi, type AdminAccess } from "@/lib/api";
import { AdminMfa } from "./AdminMfa";
import { AdminAccessContext } from "@/lib/admin-access";
import { Menu, X, ArrowUpLeft, LayoutDashboard, Package, Truck, Users, Building2, ClipboardList, Boxes, Wallet, FileText, Image, Bell, ShieldCheck, BarChart3, Settings2, History, Receipt } from "lucide-react";
import s from "./admin.module.css";
import { DashThemeToggle, useDashTheme } from "@/components/ui/DashTheme";
export const adminNavigation = [
 {label:"پیشخوان",href:"/admin",icon:LayoutDashboard}, {label:"کاتالوگ و کالاها",href:"/admin/catalog",icon:Package},
 {label:"دسته‌بندی‌ها و برندها",href:"/admin/taxonomy",icon:Boxes},
 {label:"کیفیت و انتشار کاتالوگ",href:"/admin/catalog-review",icon:ShieldCheck}, {label:"تأمین‌کنندگان و Offerها",href:"/admin/suppliers",icon:Truck},
 {label:"بررسی Offer و تاریخچه قیمت",href:"/admin/offers",icon:Truck},
 {label:"استعلام مشتریان",href:"/admin/inquiries",icon:Users}, {label:"حساب‌های سازمانی و فروشگاهی",href:"/admin/b2b",icon:Building2}, {label:"تسویه همکاران فروش",href:"/admin/affiliates",icon:Users}, {label:"سازمان‌ها و قراردادها",href:"/admin/organizations",icon:Building2},
 {label:"خرید سازمانی و پرونده‌ها",href:"/admin/cases",icon:ClipboardList}, {label:"مدیریت پک‌ها",href:"/admin/packs",icon:Boxes},
 {label:"مالی و تسویه",href:"/admin/settlements",icon:Wallet}, {label:"صورتحساب مودیان",href:"/admin/moadian",icon:Receipt}, {label:"مرجوعی‌ها",href:"/admin/returns",icon:Package},
 {label:"محتوا و ویرایش بصری",href:"/admin/content",icon:FileText}, {label:"کتابخانه رسانه",href:"/admin/media",icon:Image},
 {label:"اعلان‌ها و پیام‌ها",href:"/admin/notifications",icon:Bell}, {label:"دسترسی‌ها و سیاست‌ها",href:"/admin/access",icon:ShieldCheck},
 {label:"مشتریان شخصی",href:"/admin/customers",icon:Users}, {label:"سفارش‌های شخصی",href:"/admin/orders",icon:Package}, {label:"کاربران پلتفرم",href:"/admin/users",icon:Users},
 {label:"گزارش‌ها",href:"/admin/reports",icon:BarChart3}, {label:"تنظیمات",href:"/admin/settings",icon:Settings2}, {label:"تاریخچه تغییرات",href:"/admin/audit",icon:History},
];
// Which staff roles see each section (super-admin sees all). Mirrors backend app/core/staff_access.py;
// the backend is authoritative and still answers 403 for anything outside a role.
const SECTION_ROLES:Record<string,string[]>={"/admin":["finance","support","catalog","marketing","content","logistics"],
 "/admin/catalog":["catalog"],"/admin/taxonomy":["catalog"],"/admin/catalog-review":["catalog"],"/admin/suppliers":["catalog"],"/admin/offers":["catalog"],
 "/admin/inquiries":["support"],"/admin/affiliates":["finance"],"/admin/cases":["support"],"/admin/packs":["marketing","catalog"],
 "/admin/settlements":["finance"],"/admin/moadian":["finance"],"/admin/returns":["support"],"/admin/content":["content"],"/admin/media":["content","catalog"],
 "/admin/notifications":["marketing","support"],"/admin/customers":["support"],"/admin/orders":["support","logistics","finance"],"/admin/reports":["finance","marketing"],"/admin/mfa":["finance","support","catalog","marketing","content","logistics"]};
const canSee=(href:string,a:AdminAccess)=>a.super_admin||(SECTION_ROLES[href]??[]).some(r=>a.staff_roles.includes(r));
const EditorState=createContext<(dirty:boolean)=>void>(()=>{});
export const useAdminEditorState=()=>useContext(EditorState);
export function AdminShell({children}:{children:React.ReactNode}) {
 const {user,token,loading,logout,adminAccess}=useAuth(),path=usePathname(); const [open,setOpen]=useState(false),[dirty,setDirty]=useState(false); const [theme,toggleTheme]=useDashTheme();
 const [fetched,setFetched]=useState<AdminAccess|null>(null),[accessError,setAccessError]=useState(false);
 useEffect(()=>{setFetched(null);setAccessError(false);if(!token||adminAccess)return;let alive=true;mfaApi.status(token).then(r=>{if(alive)setFetched(r.admin_access)}).catch(()=>{if(alive)setAccessError(true)});return()=>{alive=false};},[token,adminAccess]);
 const access=adminAccess??fetched;
 const nav=access?adminNavigation.filter(n=>canSee(n.href,access)):[];
 const selected=nav.find(n=>n.href===path)??nav.find(n=>n.href!=="/admin"&&path.startsWith(n.href+"/"));
 if(loading||(user&&!access&&!accessError))return <div className={s.gate} role="status">در حال بررسی حساب و دسترسی مدیریت…</div>;
 if(!user)return <div className={s.gate}><ShieldCheck size={36}/><h1>پیشخوان مدیریت 60Online</h1><p>برای ادامه با حساب مجاز مدیریت وارد شوید.</p><Link className={s.primary} href={"/login?next="+encodeURIComponent(path)}>ورود و ادامه</Link><Link href="/">بازگشت به فروشگاه</Link></div>;
 if(!access?.is_staff)return <div className={s.gate} role="alert"><ShieldCheck size={36}/><h1>دسترسی مدیریتی لازم است</h1><p>حساب فعلی مجوز ورود به پیشخوان کسب‌وکار را ندارد.</p><Link className={s.primary} href="/account">حساب کاربری من</Link></div>;
 // Second factor: the first admin visit after deploy lands on enrollment; later visits on verification.
 if(access.mfa_required&&!access.mfa_verified)return <div className={s.gate} dir="rtl"><AdminMfa access={access}/><button onClick={()=>logout()}>خروج</button></div>;
 if(path==="/admin/content/preview")return <AdminAccessContext.Provider value={access}>{children}</AdminAccessContext.Provider>;
 const leave=()=>!dirty||window.confirm("تغییرات ذخیره‌نشده کنار گذاشته شوند؟");
 return <AdminAccessContext.Provider value={access}><EditorState.Provider value={setDirty}><div className={s.shell} dir="rtl" key={user.id}>
  {open&&<button className={s.scrim} aria-label="بستن ناوبری" onClick={()=>setOpen(false)}/>}
  <aside className={`${s.sidebar} ${open?s.open:""}`} aria-label="ناوبری مدیریت" id="admin-navigation"><div className={s.brand}><Link href="/admin" className={s.brandLink} onClick={e=>{if(!leave()){e.preventDefault();return;}setDirty(false);setOpen(false)}}><NextImage src="/brand/60online-mark.png" width={48} height={45} alt="شصت آنلاین" unoptimized/><span><span className={s.brandName}>شصت آنلاین</span><span>مدیریت کسب‌وکار</span></span></Link><button onClick={()=>setOpen(false)} aria-label="بستن منو" className={s.mobile}><X size={20}/></button></div>
   <nav>{nav.map(({label,href,icon:Icon})=><Link href={href} key={href} onClick={e=>{if(!leave()){e.preventDefault();return;}setDirty(false);setOpen(false)}} aria-current={selected?.href===href?"page":undefined} className={selected?.href===href?s.active:""}><Icon size={18}/><span>{label}</span></Link>)}</nav>
   <Link href="/" onClick={e=>{if(!leave())e.preventDefault()}} className={s.store}>مشاهده فروشگاه<ArrowUpLeft size={16}/></Link>
  </aside>
  <div className={s.body}><header className={s.topbar}><div><button className={s.mobile} onClick={()=>setOpen(true)} aria-label="بازکردن منو" aria-expanded={open} aria-controls="admin-navigation"><Menu size={22}/></button><span>پیشخوان / <b>{selected?.label??"پرونده"}</b></span></div><div><DashThemeToggle theme={theme} onToggle={toggleTheme}/><span className={s.identity}>{user.full_name||"مدیر"}</span><button onClick={()=>{if(leave())logout()}}>خروج</button></div></header><div className={s.content}>{children}</div></div>
 </div></EditorState.Provider></AdminAccessContext.Provider>;
}
