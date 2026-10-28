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
export function detectExplicitEscalation(text: string): boolean {
  return /\b(human|real person|talk to someone|call me|speak to|counsellor|counselor|connect me|escalate|help me directly|oru call|oru meeting|meeting book|book panna|book pannunga|actual person|real counsellor|baat karo|kisi se baat|insaan se|banda chahiye|madam|sir please|oru minute|direct ah|direct kku)\b/i.test(text);
}

// Classify sentiment from Gemini output label
export function parseSentimentScore(label: string): number {
  const map: Record<string, number> = {
    positive: 0.0, neutral: 0.1, mild_negative: 0.4,
    negative: 0.6, strong_negative: 0.8, distress: 1.0
  };
  return map[label.toLowerCase()] ?? 0.1;
}
