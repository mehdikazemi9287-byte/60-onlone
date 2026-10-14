"use client";
import {useEffect,useState} from "react";
import type {PageContent} from "@/lib/content-types";
import HomeSections from "@/components/home/HomeSections";
import {ContentRenderer} from "@/components/content/ContentRenderer";
export default function ContentPreview(){const [data,setData]=useState<{kind:string;content:PageContent;selected?:string}|null>(null);
 useEffect(()=>{const receive=(e:MessageEvent)=>{if(e.origin!==window.location.origin||e.source!==window.parent||e.data?.type!=='60online:content-preview')return;const d=e.data.payload;if(d&&typeof d.content?.title==='string'&&Array.isArray(d.content.blocks))setData(d)};window.addEventListener('message',receive);window.parent.postMessage({type:'60online:preview-ready'},window.location.origin);return()=>window.removeEventListener('message',receive)},[]);
 if(!data)return <p className="p-6 text-center text-sm text-neutral-500" role="status">در انتظار محتوای پیش‌نمایش مجاز…</p>;
 return <div onClickCapture={e=>{if((e.target as HTMLElement).closest('a'))e.preventDefault()}} onSubmitCapture={e=>{e.preventDefault();e.stopPropagation()}}>{data.kind==='homepage'?<HomeSections previewContent={data.content}/>:<ContentRenderer content={data.content} selected={data.selected} onSelect={id=>window.parent.postMessage({type:'60online:preview-select',id},window.location.origin)}/>}</div>;
}
