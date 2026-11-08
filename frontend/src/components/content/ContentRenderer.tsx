"use client";
import Link from "next/link";
import type {PageContent} from "@/lib/content-types";
import s from "./content.module.css";
export function ContentRenderer({content,selected,onSelect}:{content:PageContent;selected?:string;onSelect?:(id:string)=>void}){
 return <div className={s.canvas} dir="rtl">{content.blocks.filter(b=>b.enabled).map(b=><section key={b.id} className={`${s.block} ${b.type==='hero'||b.type==='banner'?s.hero:''} ${selected===b.id?s.selected:''}`} onClick={()=>onSelect?.(b.id)} tabIndex={onSelect?0:undefined} onKeyDown={e=>{if(onSelect&&(e.key==='Enter'||e.key===' ')){e.preventDefault();onSelect(b.id)}}} aria-label={onSelect?`انتخاب بلوک ${b.title||b.type}`:undefined}>
  {b.image_url&&<img src={b.image_url} alt={b.title} loading="lazy" className={s.image}/>}
  {b.title&&<h2>{b.title}</h2>}{b.body&&<p className={s.copy}>{b.body}</p>}{b.link&&<Link href={b.link} onClick={e=>{if(onSelect)e.preventDefault()}} className={s.action}>{b.button_label||"ادامه"}</Link>}
 </section>)}</div>;
}
