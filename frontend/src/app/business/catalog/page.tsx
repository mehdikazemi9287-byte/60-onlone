import { Suspense } from "react";
import BusinessCatalog from "./BusinessCatalog";
export const metadata={title:"کاتالوگ تأمین سازمانی | 60Online"};
export default function Page(){return <Suspense fallback={<p className="p-8">در حال دریافت کاتالوگ…</p>}><BusinessCatalog/></Suspense>;}
