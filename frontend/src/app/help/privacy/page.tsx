import PublishedHelp from '@/components/content/PublishedHelp';
import {publishedContent,contentMetadata} from '@/lib/published-content';
export async function generateMetadata(){return contentMetadata(await publishedContent('help-privacy'),'حریم خصوصی','/help/privacy')}
export default function Page(){return <PublishedHelp slug="privacy" title="حریم خصوصی" message="سیاست رسمی حریم خصوصی هنوز از سوی 60Online منتشر نشده است. این صفحه عمداً بدون متن حقوقی ساختگی نمایش داده می‌شود."/>}
