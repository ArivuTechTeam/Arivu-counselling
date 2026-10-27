import {requireChatGPTUser} from '../chatgpt-auth';
import AdminDesk from '@/components/admin-desk';
import {getDb} from '@/db';
import {requests} from '@/db/schema';
import {desc} from 'drizzle-orm';
export const dynamic='force-dynamic';
export default async function AdminPage(){
  const user=await requireChatGPTUser('/admin');
  if(!['marketing@arivupro.com','tech@arivupro.com'].includes(user.email.toLowerCase()))
    return <main><h1>Admin access required</h1><p>This area is restricted to the ArivuPro counselling team.</p><a href="/">Back to student enquiries</a></main>;
  let initialRows: object[] = [];
  try{ initialRows=await getDb().select().from(requests).orderBy(desc(requests.created)).limit(500); }catch{}
  return <AdminDesk initialRows={initialRows}/>;
}
