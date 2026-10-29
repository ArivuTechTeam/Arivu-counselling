import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={
  title:'ArivuPro | Counselling Desk',
  description:'A clearer next step for every commerce student.',
  icons:{
    icon:[
      {url:'/favicon.svg',type:'image/svg+xml'},
    ],
    apple:{url:'/arivupro-logo.png'},
  },
};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
