export const ESCALATION_THRESHOLD = 0.70;

export interface EscalationInput {
  sentimentScore: number;    // 0.0-1.0 from Gemini
  noMatchCount: number;      // how many times bot said NO_MATCH this session
  repeatCount: number;       // times same question asked
  explicitRequest: boolean;  // student said "human"/"call me"/"counsellor" etc.
  turnCount: number;         // total turns in session
}

export function calculateEscalationScore(input: EscalationInput): number {
  const W1 = 0.30, W2 = 0.25, W3 = 0.20, W4 = 0.25;
  const confusionScore = Math.min(input.noMatchCount * 0.3, 1.0);
  const repeatScore    = Math.min(input.repeatCount * 0.5, 1.0);
  const explicitScore  = input.explicitRequest ? 1.0 : 0.0;
  let score = (W1 * input.sentimentScore) + (W2 * confusionScore) +
              (W3 * repeatScore) + (W4 * explicitScore);
  // session length boost: 8+ turns with no resolution
  if (input.turnCount >= 8) score += 0.15;
  return Math.min(score, 1.0);
}

// Detect explicit escalation keywords in any language (English + Tanglish + Hinglish)
// Covers natural phrasings: "need to connect", "I want to talk", "connect a call", etc.
export function detectExplicitEscalation(text: string): boolean {
  const t = text.toLowerCase();

  // English — broad semantic coverage of "I want to speak to a human/counsellor"
  const englishPatterns = [
    /\b(human|real person|actual person|real counsellor|real counselor)\b/,
    /\bspeak\s+(to|with)\b/,
    /\btalk\s+(to|with)\b/,
    /\bchat\s+with\s+(someone|a\s+person|counsellor|counselor|team|you)\b/,
    /\b(call\s*me|give\s*me\s*a\s*call|make\s*a\s*call|connect\s*a?\s*call|need\s*a\s*call|want\s*a\s*call|phone\s*call)\b/,
    /\bconnect\s*(me|with|a|to)\b/,
    /\bi\s*(need|want|would\s+like)\s*(to\s*)?(talk|speak|connect|call|chat|meet|discuss)\b/,
    /\b(need|want)\s+(to\s+)?(connect|reach|contact)\b/,
    /\bbook\s+(a\s+)?(call|meeting|session|slot)\b/,
    /\bschedule\s+(a\s+)?(call|meeting|session)\b/,
    /\b(counsellor|counselor|advisor|adviser|mentor|expert|team|staff)\s*(se|ko|kitte|kitta|kitte|please)?\b/,
    /\bescalate\b/,
    /\bhelp\s+me\s+directly\b/,
    /\btalk\s+to\s+someone\b/,
    /\bsomebody\s+to\s+talk\b/,
    /\bsomeone\s+to\s*(help|talk|speak|call)\b/,
    /\bget\s+in\s+touch\b/,
    /\breach\s+out\b/,
    /\bcontact\s+(me|you|team|someone)\b/,
  ];

  // Tanglish / Tamil
  const tanglishPatterns = [
    /\b(oru\s*call|oru\s*meeting|call\s*panna|call\s*pannunga|meeting\s*book|book\s*panna|book\s*pannunga)\b/,
    /\b(direct\s*ah|direct\s*kku|directly\s*pesu|counsellor\s*kitte|team\s*kitte|kitta\s*pesu)\b/,
    /\b(pesa\s*venum|pesuven|pesunga|connect\s*panna|connect\s*pannunga)\b/,
    /\b(unga\s*kitte|unna\s*kitte|counselor\s*kitte)\b/,
  ];

  // Hinglish / Hindi
  const hinglishPatterns = [
    /\b(baat\s*karo|baat\s*karna|baat\s*karni|baat\s*karte|kisi\s*se\s*baat|insaan\s*se|banda\s*chahiye)\b/,
    /\b(call\s*karo|call\s*karna|call\s*chahiye|mujhe\s*call|call\s*lagao)\b/,
    /\b(milna\s*hai|milna\s*chahta|meeting\s*chahiye|appointment\s*chahiye)\b/,
    /\b(kisi\s*se|aap\s*se|counsellor\s*se)\s*(baat|connect|milna|call)\b/,
  ];

  return (
    englishPatterns.some(p => p.test(t)) ||
    tanglishPatterns.some(p => p.test(t)) ||
    hinglishPatterns.some(p => p.test(t))
  );
}

// Classify sentiment from Gemini output label
export function parseSentimentScore(label: string): number {
  const map: Record<string, number> = {
    positive: 0.0, neutral: 0.1, mild_negative: 0.4,
    negative: 0.6, strong_negative: 0.8, distress: 1.0
  };
  return map[label.toLowerCase()] ?? 0.1;
}
