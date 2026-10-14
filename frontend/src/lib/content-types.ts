export type ContentBlock={id:string;type:"hero"|"text"|"banner"|"cta"|"home_section";title:string;body:string;link:string;button_label:string;image_url:string;enabled:boolean;key?:string};
export type PageContent={title:string;blocks:ContentBlock[];seo?:{title:string;description:string;canonical:string;noindex:boolean}};
export type ContentPage={id:number;slug:string;title:string;kind:"page"|"article"|"homepage";draft_revision_id:number;published_revision_id:number|null;content:PageContent};
export const homeSections:Record<string,string>={hero:"معرفی و اقدام اصلی",collections:"مجموعه‌های تأمین",categories:"دسته‌بندی‌ها",today:"کالاهای امروز",why:"مزیت‌های خرید",groups:"گروه‌های کالایی",brands:"برندها",packs:"پک‌های آماده",organization:"خدمات سازمانی"};
