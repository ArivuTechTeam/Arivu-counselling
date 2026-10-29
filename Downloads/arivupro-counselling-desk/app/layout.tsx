import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={
  title:'ArivuPro | Counselling Desk',
  description:'A clearer next step for every commerce student.',
  icons:{
    icon:[
      {url:'/favicon.jpg',type:'image/jpeg'},
    ],
    apple:{url:'/favicon.jpg'},
  },
};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
