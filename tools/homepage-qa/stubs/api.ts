// LOCAL QA FIXTURE ONLY — never shipped. Names/images mirror real catalog files in the repo.
const C='/images/catalog/';
const cat=(slug:string,name:string,product_count:number)=>({slug,name,product_count});
const supermarket=cat('supermarket','سوپرمارکت',406),nuts=cat('nuts','آجیل و خشکبار',339),stationery=cat('stationery','نوشت‌افزار',224),protein=cat('protein','مواد پروتئینی',203),dairy=cat('dairy','لبنیات، میوه و منجمد',188);
const P=(id:number,name:string,img:string,c:any,brand?:string)=>({id,slug:'p'+id,name,description:'',price_minor:null,purchasable:false,image_url:C+img,category:c,brand});
const items=[P(1,'پسته','04ae4003f2e4ed1a7d1f59ea2e76b3605505b0f3e7853fd872062483d820472b.jpg',nuts),P(2,'روغن خوراکی ۱۶ کیلوگرمی','6a77b46f318343d639794b427b2809733dfcf2d8bcd90dacf861a5ffce838070.png',supermarket,'طبیعت'),P(3,'شیر پرچرب ۳٪','0d50df9b3570c6ff39e5af44b0d65bce5f7131461fb34e6dfc654fdf13a435a4.png',dairy,'کاله'),P(4,'ماست چکیده کفیر ناری ۷۵۰ گرمی','3f443d3d2d45ecdb5f90258e7d2543535ecaf65c880a7e6b280158241bdded6f.png',dairy,'کاله'),P(5,'پنیر لبنه آنا ۳۵۰ گرمی','951d2e32c9b8d630f4abac03a28882002d7a2a6f2ac8ee490b7099f7481fe54a.png',dairy,'کاله'),P(6,'بستنی ژلاتو آلو فوردو','97145565a68969e07a87451edc0df3bf43088903907fc64ad4e8710e31cef978.png',dairy,'کاله'),P(7,'آجیل مخلوط','c5bc3d33018a27ed4bb1ff3c4bd954d08bdb1306c8489ce91fd05eb841904135.jpg',nuts),P(8,'تخمه کدو گوشتی','31f848541444384157f156c3ab1212a08c97c39ccfa4f5020e6d6db49f9f19f0.jpg',nuts)];
export const catalog={list:async()=>({items,total:items.length})};
export const categories={list:async()=>[supermarket,nuts,stationery,protein,dairy]};
export const apiRequest=async()=>{throw new Error('offline')};
export const cart={get:async()=>({item_count:0})};
