import PublishedHelp from '@/components/content/PublishedHelp';
import {publishedContent,contentMetadata} from '@/lib/published-content';
export async function generateMetadata(){return contentMetadata(await publishedContent('help-buying'),'راهنمای خرید','/help/buying')}
export default function Page(){return <PublishedHelp slug="buying" title="راهنمای خرید" message="راهنمای رسمی خرید هنوز منتشر نشده است. برای خرید، محصول موجود را به سبد اضافه کنید و مراحل تسویه‌حساب را ادامه دهید."/>}
