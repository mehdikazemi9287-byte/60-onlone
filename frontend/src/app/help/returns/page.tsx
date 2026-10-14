import PublishedHelp from '@/components/content/PublishedHelp';
import {publishedContent,contentMetadata} from '@/lib/published-content';
export async function generateMetadata(){return contentMetadata(await publishedContent('help-returns'),'شرایط بازگشت کالا','/help/returns')}
export default function Page(){return <PublishedHelp slug="returns" title="شرایط بازگشت کالا" message="سیاست رسمی بازگشت کالا هنوز از سوی 60Online منتشر نشده است. تا زمان انتشار، این صفحه هیچ شرطی را به‌صورت ساختگی اعلام نمی‌کند."/>}
