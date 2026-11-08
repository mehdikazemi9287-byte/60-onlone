import ProductIdentityEditor from "@/components/admin/ProductIdentityEditor";
import {notFound} from "next/navigation";
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;if(!/^[1-9][0-9]*$/.test(id)||!Number.isSafeInteger(Number(id)))notFound();return <ProductIdentityEditor id={Number(id)}/>;}
