export const useGoodImages=(urls:any[])=>new Set(urls);
export const storefront={brands:async()=>({items:[['تواضع',324],['کاله',305],['آریا',224],['گلستان',100],['سورین',81],['هاتی کارا',69],['طبیعت',49],['شمس',31]].map(([name,product_count])=>({name,product_count,image_url:null}))})};
export type PackDetail=any;
export const UI={ ink: "#112D46", mint: "#EDF3EE", warm: "#F8F7F4", line: "#DFE5E9", muted: "#526778" };
export const PackCard=({p}:any)=><div className="h-40 rounded-2xl bg-white p-4">{p.slug}</div>;
const I=(f:string)=>({image_url:'/images/catalog/'+f});
export const loadPackDetails=async()=>[{slug:'family-daily',title_fa:'پک روزمرهٔ خانواده',purpose_fa:'اقلام اصلی خانه: برنج، روغن و لبنیات',item_count:8,items:[I('6a77b46f318343d639794b427b2809733dfcf2d8bcd90dacf861a5ffce838070.png'),I('0d50df9b3570c6ff39e5af44b0d65bce5f7131461fb34e6dfc654fdf13a435a4.png')]},{slug:'gathering-tea',title_fa:'پک دورهمی و دمنوش',purpose_fa:'پذیرایی دورهمی',item_count:3,items:[I('c5bc3d33018a27ed4bb1ff3c4bd954d08bdb1306c8489ce91fd05eb841904135.jpg'),I('04ae4003f2e4ed1a7d1f59ea2e76b3605505b0f3e7853fd872062483d820472b.jpg')]},{slug:'employee-gift',title_fa:'هدیهٔ کارکنان',purpose_fa:'هدیهٔ مناسبتی برای کارکنان',item_count:3,items:[I('31f848541444384157f156c3ab1212a08c97c39ccfa4f5020e6d6db49f9f19f0.jpg')]}];
export function packImages(p:any,good:any,max=3,used?:Set<string>){const o:string[]=[];for(const i of p.items)if(!used?.has(i.image_url)&&o.length<max)o.push(i.image_url);o.forEach(u=>used?.add(u));return o}
export const formatTomanExact=(n:number)=>n+' تومان';
export const toPersianNum=(n:any)=>String(n).replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[+d]);
export const cn=(...a:any[])=>a.filter(Boolean).join(' ');
