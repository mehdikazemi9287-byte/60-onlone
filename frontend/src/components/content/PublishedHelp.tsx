import {ContentRenderer} from './ContentRenderer';
import {UnavailablePage} from './UnavailablePage';
import {publishedContent} from '@/lib/published-content';
export default async function PublishedHelp({slug,title,message}:{slug:string;title:string;message:string}){const d=await publishedContent('help-'+slug);if(!d||d.kind!=='page')return <UnavailablePage title={title} message={message}/>;return <article className="mx-auto w-full max-w-[1280px] px-4 py-8"><h1 className="px-6 text-2xl font-bold">{d.content.title}</h1><ContentRenderer content={d.content}/></article>}
