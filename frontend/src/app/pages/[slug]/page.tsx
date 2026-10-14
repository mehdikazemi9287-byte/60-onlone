import {notFound} from "next/navigation";
import {ContentRenderer} from "@/components/content/ContentRenderer";
import {publishedContent,contentMetadata} from "@/lib/published-content";
const load=publishedContent;
export async function generateMetadata({params}:{params:Promise<{slug:string}>}){const {slug}=await params;const d=await load(slug);return contentMetadata(d,"صفحه","/pages/"+slug);}
export default async function Page({params}:{params:Promise<{slug:string}>}){const {slug}=await params;const d=await load(slug);if(!d||d.kind==="homepage")notFound();return <article className="mx-auto w-full max-w-[1280px] px-4 py-8"><h1 className="px-6 text-2xl font-bold">{d.content.title}</h1><ContentRenderer content={d.content}/></article>;}
