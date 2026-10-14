import PublishedHelp from '@/components/content/PublishedHelp';
import {publishedContent,contentMetadata} from '@/lib/published-content';
export async function generateMetadata(){return contentMetadata(await publishedContent('help-terms'),'شرایط استفاده','/help/terms')}
export default function Page(){return <PublishedHelp slug="terms" title="شرایط استفاده" message="متن رسمی شرایط استفاده هنوز از سوی 60Online منتشر نشده است. این صفحه عمداً بدون متن حقوقی ساختگی نمایش داده می‌شود."/>}
