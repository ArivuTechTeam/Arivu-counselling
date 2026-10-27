import {cookies} from 'next/headers';

const ALLOWED_EMAILS = ['marketing@arivupro.com','tech@arivupro.com'];

export async function POST(req: Request) {
  const {email, password} = await req.json();
  const adminPassword = process.env.ADMIN_PASSWORD;

  if (!adminPassword) return Response.json({error:'ADMIN_PASSWORD not configured'},{status:500});
  if (!ALLOWED_EMAILS.includes((email||'').toLowerCase().trim())) return Response.json({error:'That email is not authorised for admin access'},{status:401});
  if (password !== adminPassword) return Response.json({error:'Incorrect password'},{status:401});

  const jar = await cookies();
  jar.set('admin_token', adminPassword, {
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    maxAge: 60 * 60 * 8, // 8 hours
    path: '/',
  });

  return Response.json({ok: true});
}

// Logout
export async function DELETE() {
  const jar = await cookies();
  jar.delete('admin_token');
  return Response.json({ok: true});
}
