import PublishedHelp from '@/components/content/PublishedHelp';
import {publishedContent,contentMetadata} from '@/lib/published-content';
export async function generateMetadata(){return contentMetadata(await publishedContent('help-faq'),'سوالات متداول','/help/faq')}
export default function Page(){return <PublishedHelp slug="faq" title="سوالات متداول" message="پاسخ‌های رسمی این بخش هنوز منتشر نشده‌اند."/>}
