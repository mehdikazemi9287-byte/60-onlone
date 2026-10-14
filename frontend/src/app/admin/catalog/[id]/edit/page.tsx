import ProductContentEditor from "@/components/admin/ProductContentEditor";
import {notFound} from "next/navigation";
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;if(!/^[1-9][0-9]*$/.test(id)||!Number.isSafeInteger(Number(id)))notFound();return <ProductContentEditor id={Number(id)}/>;}
