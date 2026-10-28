export interface SlotData {
  name?: string;
  phone?: string;
  email?: string;
  course?: string;
}

export function extractSlots(text: string): SlotData {
  const result: SlotData = {};

  // Indian 10-digit mobile
  const phone = text.match(/\b[6-9]\d{9}\b/);
  if (phone) result.phone = phone[0];

  // Email
  const email = text.match(/\b[\w.+\-]+@[\w\-]+\.[a-z]{2,}\b/i);
  if (email) result.email = email[0].toLowerCase();

  // Name patterns: "I am X", "naan X", "my name is X", "peru X", "I'm X"
  const nameMatch = text.match(
    /(?:i(?:'?m| am)|naan|my name is|peru\s*[:=]?\s*|name[:\s]+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i
  );
  if (nameMatch) result.name = nameMatch[1].trim();

  // Course mentions
  const courseMap: Record<string, string> = {
    'ca foundation': 'CA Foundation', 'ca inter': 'CA Inter', 'ca final': 'CA Final',
    'cma india': 'CMA India', 'cma foundation': 'CMA India',
    'us cma': 'US CMA', 'cma usa': 'US CMA',
    'acca': 'ACCA', 'cfa': 'CFA', 'frm': 'FRM',
    'cpa': 'CPA', 'cs foundation': 'CS', 'company secretary': 'CS'
  };
  const lower = text.toLowerCase();
  for (const [key, val] of Object.entries(courseMap)) {
    if (lower.includes(key)) { result.course = val; break; }
  }

  return result;
}

export function mergeSlots(existing: SlotData, incoming: SlotData): SlotData {
  return {
    name:   incoming.name   || existing.name,
    phone:  incoming.phone  || existing.phone,
    email:  incoming.email  || existing.email,
    course: incoming.course || existing.course,
  };
}

export function missingSlots(slots: SlotData): string[] {
  const missing: string[] = [];
  if (!slots.name)  missing.push('name');
  if (!slots.phone) missing.push('phone');
  if (!slots.email) missing.push('email');
  return missing;
}
