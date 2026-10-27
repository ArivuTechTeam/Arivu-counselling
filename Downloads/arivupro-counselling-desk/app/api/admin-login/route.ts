import {cookies} from 'next/headers';

export async function POST(req: Request) {
  const {password} = await req.json();
  const adminPassword = process.env.ADMIN_PASSWORD;

  if (!adminPassword) {
    return Response.json({error: 'ADMIN_PASSWORD not configured'}, {status: 500});
  }
  if (password !== adminPassword) {
    return Response.json({error: 'Incorrect password'}, {status: 401});
  }

  const jar = await cookies();
  jar.set('admin_token', adminPassword, {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: '/',
  });

  return Response.json({ok: true});
}
