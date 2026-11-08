export const useGoodImages=(urls:any[])=>new Set(urls);
export const storefront={brands:async()=>({items:[['تواضع',324],['کاله',305],['آریا',224],['گلستان',100],['سورین',81],['هاتی کارا',69],['طبیعت',49],['شمس',31]].map(([name,product_count])=>({name,product_count,image_url:null}))})};
export type PackDetail=any;
export const UI={ ink: "#112D46", mint: "#EDF3EE", warm: "#F8F7F4", line: "#DFE5E9", muted: "#526778" };
export const PackCard=({p}:any)=><div className="h-40 rounded-2xl bg-white p-4">{p.slug}</div>;
export const loadPackDetails=async()=>[{slug:'employee-gift',items:[1]},{slug:'family-daily',items:[1]},{slug:'gathering-tea',items:[1]}];
export const formatTomanExact=(n:number)=>n+' تومان';
export const toPersianNum=(n:any)=>String(n).replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[+d]);
