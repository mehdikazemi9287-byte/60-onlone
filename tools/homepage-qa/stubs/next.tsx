export default function Image({src,alt,className,fill,sizes,priority,...r}:any){return <img src={src} alt={alt} className={className} style={fill?{position:'absolute',inset:0,width:'100%',height:'100%'}:undefined} {...r}/>}
export const usePathname=()=>'/';
export const useAuth=()=>({user:null,token:null,loading:false});
export const cn=(...a:any[])=>a.filter(Boolean).join(' ');
