import {createRoot} from 'react-dom/client';
import Home from '@/components/home/HomeSections';
import {Header} from '@/components/layout/Header';
import {Footer} from '@/components/layout/Footer';
createRoot(document.getElementById('root')!).render(<><Header/><Home/><Footer/></>);
