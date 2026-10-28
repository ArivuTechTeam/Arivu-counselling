import { talkingPoints } from './counselling-answers';
import { getDb } from '../db';
import { wpData } from '../db/schema';
import { like, or, desc } from 'drizzle-orm';

export interface KnowledgeResult {
  type: 'curated' | 'wp' | 'none';
  scriptId?: string;
  scriptTitle?: string;
  scriptAnswer?: string;
  scriptFollowups?: string[];
  scriptVerify?: string;
  wpContent?: string;
}

// Build compact script index for Gemini classifier (same as assistant route)
export const scriptIndex = talkingPoints.map((p, i) => `${i}. [${p.id}] ${p.title}`).join('\n');

// Look up wp_data table for batch/fee/schedule context
export async function lookupWpData(query: string): Promise<string> {
  try {
    const db = getDb();
    const terms = query.toLowerCase().split(/\s+/).filter(w => w.length > 3).slice(0, 4);
    if (terms.length === 0) return '';

    const conditions = terms.map(t =>
      or(like(wpData.title, `%${t}%`), like(wpData.content, `%${t}%`))
    );

    const rows = await db.select({
      title: wpData.title,
      content: wpData.content,
      acfFields: wpData.acfFields,
      updatedAt: wpData.updatedAt,
    })
    .from(wpData)
    .where(or(...conditions))
    .orderBy(desc(wpData.updatedAt))
    .limit(3);

    if (rows.length === 0) return '';

    return rows.map((r: { title: string; content: string; acfFields: string; updatedAt: string }) => {
      let text = `[${r.title}]: ${r.content.slice(0, 400)}`;
      if (r.acfFields) {
        try {
          const acf = JSON.parse(r.acfFields) as Record<string, string>;
          const parts: string[] = [];
          if (acf.next_batch_date) parts.push(`Next batch: ${acf.next_batch_date}`);
          if (acf.fee) parts.push(`Fee: ${acf.fee}`);
          if (acf.batch_type) parts.push(`Type: ${acf.batch_type}`);
          if (acf.batch_status) parts.push(`Status: ${acf.batch_status}`);
          if (parts.length > 0) text += ` | ${parts.join(' | ')}`;
        } catch {}
      }
      return text;
    }).join('\n\n');
  } catch {
    return '';
  }
}
