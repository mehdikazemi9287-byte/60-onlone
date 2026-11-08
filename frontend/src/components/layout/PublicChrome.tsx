"use client";
import {usePathname} from "next/navigation";
import {Header} from "./Header";
import {Footer} from "./Footer";
import {VambiShell} from "@/components/vambi/VambiShell";
export function PublicChrome({children}:{children:React.ReactNode}){const path=usePathname();if(path==="/vambi"||path.startsWith("/vambi/"))return <VambiShell>{children}</VambiShell>;if(path==="/admin"||path.startsWith("/admin/"))return <main className="flex-1">{children}</main>;return <><Header/><main className="flex-1">{children}</main><Footer/></>;}
