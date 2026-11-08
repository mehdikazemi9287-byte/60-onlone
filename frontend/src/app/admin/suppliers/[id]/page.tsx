import SupplierProfile from '@/components/admin/SupplierProfile';
export const metadata={title:'پرونده تأمین‌کننده | 60Online',robots:{index:false,follow:false}};
export default async function Page({params}:{params:Promise<{id:string}>}){const{id}=await params;return <SupplierProfile id={Number(id)}/>}
