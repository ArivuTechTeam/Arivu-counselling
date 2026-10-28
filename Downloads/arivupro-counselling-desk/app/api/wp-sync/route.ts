import { getDb } from '@/db';
import { wpData } from '@/db/schema';
import { eq } from 'drizzle-orm';
export const dynamic = 'force-dynamic';

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, ' ')
    .trim();
}

export async function POST(req: Request) {
  // 1. Verify secret token
  const secret = req.headers.get('x-wp-secret');
  const expected = process.env.WP_WEBHOOK_SECRET;
  if (expected && secret !== expected) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    const body = await req.json() as Record<string, unknown>;

    // WP Webhooks plugin sends data in this structure:
    // body.post_data or body directly with post_title, post_content, post_name, post_status
    // Also supports ACF fields in body.acf or body.post_data.acf

    const postData = (body.post_data || body) as Record<string, string>;
    const title = stripHtml(postData.post_title || '');
    const slug = postData.post_name || postData.post_slug || title.toLowerCase().replace(/\s+/g, '-');
    const rawContent = postData.post_content || '';
    const content = stripHtml(rawContent).slice(0, 2000);
    const postStatus = postData.post_status || 'publish';

    // Only sync published pages/posts
    if (postStatus !== 'publish') {
      return Response.json({ ok: true, skipped: true, reason: 'not published' });
    }

    // Extract ACF fields if present
    const acf = (postData.acf || body.acf || {}) as Record<string, string>;
    const acfFields = JSON.stringify({
      next_batch_date: acf.next_batch_date || acf['next-batch-date'] || '',
      fee: acf.course_fee || acf.fee || '',
      batch_type: acf.batch_type || acf['batch-type'] || '',
      batch_status: acf.batch_status || acf['batch-status'] || '',
      batch_notes: acf.batch_notes || acf['batch-notes'] || '',
    });

    const now = new Date().toISOString();
    const db = getDb();

    // Upsert: update if slug exists, insert if new
    const existing = await db.select({ id: wpData.id })
      .from(wpData)
      .where(eq(wpData.pageSlug, slug))
      .limit(1);

    if (existing.length > 0) {
      await db.update(wpData)
        .set({ title, content, acfFields, updatedAt: now })
        .where(eq(wpData.pageSlug, slug));
    } else {
      await db.insert(wpData).values({ pageSlug: slug, title, content, acfFields, updatedAt: now });
    }

    return Response.json({ ok: true, slug, title, acfParsed: JSON.parse(acfFields) });

  } catch (err) {
    return Response.json({ error: 'Failed to process webhook', detail: String(err) }, { status: 500 });
  }
}

// GET — health check so WP Webhooks can verify the endpoint
export async function GET() {
  return Response.json({ ok: true, endpoint: 'ArivuPro WP Sync', version: '1.0' });
}
