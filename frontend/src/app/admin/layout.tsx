export const metadata={robots:{index:false,follow:false}};
import {AdminShell} from "@/components/admin/AdminShell";
export default function Layout({children}:{children:React.ReactNode}){return <AdminShell>{children}</AdminShell>;}
