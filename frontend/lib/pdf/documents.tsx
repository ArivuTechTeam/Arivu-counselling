import {
  Document,
  Font,
  Image,
  Page,
  StyleSheet,
  Text,
  View,
} from "@react-pdf/renderer";

import { PdfBranding, resolvedPdfBranding } from "./branding";
export type { PdfBranding } from "./branding";
export { resolvedPdfBranding } from "./branding";

Font.register({
  family: "Noto Sans",
  fonts: [
    { src: "/fonts/NotoSans-Regular.ttf", fontWeight: 400 },
    { src: "/fonts/NotoSans-Bold.ttf", fontWeight: 700 },
  ],
});
// Preserve technical terms, formulas, names, and non-English words exactly as
// authored instead of inserting language-dependent automatic hyphens.
Font.registerHyphenationCallback((word) => [word]);

// --- shared look --------------------------------------------------------------
const BRAND = "#15603d";
const s = StyleSheet.create({
  page: {
    paddingTop: 40,
    paddingBottom: 46,
    paddingHorizontal: 44,
    fontSize: 11,
    color: "#1a1a1a",
    fontFamily: "Noto Sans",
    lineHeight: 1.4,
  },
  headerBar: {
    borderBottomWidth: 2,
    borderBottomColor: BRAND,
    paddingBottom: 8,
    marginBottom: 16,
  },
  brand: { fontSize: 9, color: BRAND, fontFamily: "Noto Sans", fontWeight: 700, letterSpacing: 1 },
  title: { fontSize: 16, fontFamily: "Noto Sans", fontWeight: 700, marginTop: 4 },
  meta: { fontSize: 9, color: "#666", marginTop: 4 },
  sectionTitle: {
    fontSize: 11,
    fontFamily: "Noto Sans",
    fontWeight: 700,
    color: BRAND,
    marginTop: 14,
    marginBottom: 6,
  },
  qBlock: { marginBottom: 11 },
  qText: { fontFamily: "Noto Sans", fontWeight: 700, marginBottom: 3 },
  option: { marginLeft: 12, marginBottom: 1.5 },
  answer: { marginTop: 3, color: BRAND, fontSize: 10 },
  explanation: { marginTop: 1.5, color: "#666", fontSize: 9 },
  summaryRow: { flexDirection: "row", marginBottom: 14 },
  summaryBox: {
    padding: 8,
    borderWidth: 1,
    borderColor: "#e5e5e5",
    borderRadius: 4,
    flexGrow: 1,
    marginRight: 8,
  },
  bigNum: { fontSize: 18, fontFamily: "Noto Sans", fontWeight: 700 },
  small: { fontSize: 8, color: "#666", marginTop: 2 },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#eee",
  },
  tag: { fontSize: 9, fontFamily: "Noto Sans", fontWeight: 700 },
  footer: {
    position: "absolute",
    bottom: 24,
    left: 44,
    right: 44,
    fontSize: 8,
    color: "#999",
    textAlign: "center",
  },
});

const LETTER = ["A", "B", "C", "D", "E", "F", "G", "H"];

type Option = { id: string; text: string };
type Q = {
  type: string;
  question_text: string;
  options?: Option[] | null;
  correct_answer: unknown;
  explanation?: string | null;
  marks?: number | null;
  number?: string;
  model_answer?: string | null;
};

function marksOf(q: { marks?: number | null }) {
  return Number(q.marks) || 1;
}

const SUPERSCRIPT_DIGITS: Record<string, string> = {
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

// Render ordinary caret exponents cleanly without attempting to reinterpret
// variables or rewrite the mathematical meaning supplied by the generator.
function displayText(value: unknown): string {
  return String(value ?? "").replace(/\^([0-9]+)/g, (_match, digits: string) =>
    digits.split("").map((digit) => SUPERSCRIPT_DIGITS[digit] ?? digit).join(""),
  );
}

// Turn a raw answer value into readable text (maps MCQ ids to "A. text").
function answerText(value: unknown, options?: Option[] | null): string {
  if (value == null) return "—";
  if (options && options.length) {
    const one = (id: string) => {
      const i = options.findIndex((o) => o.id === id);
      return i >= 0 ? `${LETTER[i] ?? i + 1}. ${displayText(options[i].text)}` : displayText(id);
    };
    if (Array.isArray(value)) return value.map((v) => one(String(v))).join(", ");
    if (typeof value === "string") return one(value);
  }
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if ("value" in o) {
      return displayText(`${o.value}${o.tolerance ? ` (±${o.tolerance})` : ""}`);
    }
    if ("answers" in o) return (o.answers as string[]).map(displayText).join(" / ");
  }
  return displayText(value);
}

function PaperHeader({ branding, title, meta }: { branding?: PdfBranding | null; title: string; meta?: string }) {
  const brand = resolvedPdfBranding(branding);
  return (
    <View style={{ ...s.headerBar, borderBottomColor: brand.primary_color }}>
      {brand.logo_url ? (
        // React PDF's Image is not a DOM image and has no alt prop.
        // eslint-disable-next-line jsx-a11y/alt-text
        <Image src={brand.logo_url} style={{ width: 90, height: 34, objectFit: "contain", marginBottom: 4 }} />
      ) : null}
      <Text style={{ ...s.brand, color: brand.primary_color }}>{brand.name.toUpperCase()}</Text>
      <Text style={s.title}>{title}</Text>
      {meta ? <Text style={s.meta}>{meta}</Text> : null}
    </View>
  );
}

function Footer({ branding }: { branding?: PdfBranding | null }) {
  return <Text style={s.footer} fixed>Generated for {resolvedPdfBranding(branding).name}</Text>;
}

// --- 1) Question paper --------------------------------------------------------
export function QuestionPaperDoc({
  title,
  meta,
  questions = [],
  sections,
  withAnswers,
  branding,
}: {
  title: string;
  meta?: string;
  questions?: Q[];
  sections?: { title: string; questions: Q[] }[];
  withAnswers: boolean;
  branding?: PdfBranding | null;
}) {
  const paperSections = sections?.length
    ? sections
    : [{ title: "", questions }];
  const questionCount = paperSections.reduce(
    (sum, section) => sum + section.questions.length,
    0,
  );
  const totalMarks = paperSections.reduce(
    (sum, section) =>
      sum + section.questions.reduce((sectionSum, q) => sectionSum + marksOf(q), 0),
    0,
  );
  return (
    <Document title={title}>
      <Page size="A4" style={s.page}>
        <PaperHeader
          branding={branding}
          title={title}
          meta={`${[meta, `${questionCount} questions`, `${totalMarks} marks`].filter(Boolean).join("   ·   ")}${withAnswers ? "   ·   ANSWER KEY" : ""}`}
        />
        {paperSections.map((section, sectionIndex) => (
          <View key={sectionIndex}>
            {paperSections.length > 1 && (
              <Text style={s.sectionTitle}>{section.title}</Text>
            )}
            {section.questions.map((q, i) => (
              <View key={i} style={s.qBlock} wrap={false}>
                <Text style={s.qText}>
                  {i + 1}. {displayText(q.question_text)}  ({marksOf(q)} {marksOf(q) === 1 ? "mark" : "marks"})
                </Text>
                {q.options?.map((o, oi) => (
                  <Text key={oi} style={s.option}>
                    {LETTER[oi] ?? oi + 1}. {displayText(o.text)}
                  </Text>
                ))}
                {q.type === "fill_blank" && !q.options && (
                  <Text style={s.option}>______________________________</Text>
                )}
                {withAnswers && (
                  <Text style={s.answer}>
                    Answer: {answerText(q.correct_answer, q.options)}
                  </Text>
                )}
                {withAnswers && q.explanation ? (
                  <Text style={s.explanation}>Why: {displayText(q.explanation)}</Text>
                ) : null}
              </View>
            ))}
          </View>
        ))}
        <Footer branding={branding} />
      </Page>
    </Document>
  );
}

// --- 2) Report card (student, one quiz) --------------------------------------
type ResultQ = Q & {
  is_correct?: boolean | null;
  student_answer?: unknown;
  marks_awarded?: number | null;
};
export function ReportCardDoc({
  studentName,
  quizTitle,
  score,
  maxScore,
  date,
  results,
  branding,
}: {
  studentName?: string;
  quizTitle: string;
  score: number;
  maxScore: number;
  date?: string;
  results: ResultQ[];
  branding?: PdfBranding | null;
}) {
  const pct = maxScore ? Math.round((score / maxScore) * 100) : 0;
  const correct = results.filter((r) => r.is_correct).length;
  return (
    <Document title={`Report card — ${quizTitle}`}>
      <Page size="A4" style={s.page}>
        <PaperHeader branding={branding} title="Report Card" meta={[studentName, quizTitle, date].filter(Boolean).join("   ·   ")} />
        <View style={s.summaryRow}>
          <View style={s.summaryBox}>
            <Text style={{ ...s.bigNum, color: pct >= 60 ? BRAND : "#c02" }}>{pct}%</Text>
            <Text style={s.small}>SCORE</Text>
          </View>
          <View style={s.summaryBox}>
            <Text style={s.bigNum}>
              {correct}/{results.length}
            </Text>
            <Text style={s.small}>CORRECT</Text>
          </View>
          <View style={{ ...s.summaryBox, marginRight: 0 }}>
            <Text style={s.bigNum}>
              {score}/{maxScore}
            </Text>
            <Text style={s.small}>MARKS</Text>
          </View>
        </View>
        {results.map((r, i) => (
          <View key={i} style={s.qBlock} wrap={false}>
            <Text style={s.qText}>
              <Text style={{ ...s.tag, color: r.is_correct ? BRAND : "#c02" }}>
                {r.is_correct ? "[Correct] " : "[Wrong] "}
              </Text>
              {i + 1}. {displayText(r.question_text)}
            </Text>
            <Text style={s.option}>
              Your answer: {answerText(r.student_answer, r.options)}
            </Text>
            {!r.is_correct && (
              <Text style={s.answer}>
                Correct answer: {answerText(r.correct_answer, r.options)}
              </Text>
            )}
          </View>
        ))}
        <Footer branding={branding} />
      </Page>
    </Document>
  );
}

// --- 3) Student report (teacher, overall) ------------------------------------
export function StudentReportDoc({
  studentName,
  overall,
  perQuiz,
  weakAreas,
  branding,
}: {
  studentName: string;
  overall: { accuracy: number; quizzes_taken: number; questions_answered: number };
  perQuiz: { title: string; accuracy: number; date: string | null }[];
  weakAreas: { topic: string; accuracy: number; answered: number }[];
  branding?: PdfBranding | null;
}) {
  return (
    <Document title={`Student report — ${studentName}`}>
      <Page size="A4" style={s.page}>
        <PaperHeader branding={branding} title={`Student Report — ${studentName}`} meta="Overall performance across your quizzes" />
        <View style={s.summaryRow}>
          <View style={s.summaryBox}>
            <Text style={{ ...s.bigNum, color: overall.accuracy >= 60 ? BRAND : "#c02" }}>
              {overall.accuracy}%
            </Text>
            <Text style={s.small}>AVG ACCURACY</Text>
          </View>
          <View style={s.summaryBox}>
            <Text style={s.bigNum}>{overall.quizzes_taken}</Text>
            <Text style={s.small}>QUIZZES TAKEN</Text>
          </View>
          <View style={{ ...s.summaryBox, marginRight: 0 }}>
            <Text style={s.bigNum}>{overall.questions_answered}</Text>
            <Text style={s.small}>QUESTIONS</Text>
          </View>
        </View>

        <Text style={s.sectionTitle}>Per-quiz scores</Text>
        {perQuiz.length === 0 ? (
          <Text style={s.meta}>No graded quizzes yet.</Text>
        ) : (
          perQuiz.map((q, i) => (
            <View key={i} style={s.row}>
              <Text>{q.title}</Text>
              <Text>{q.accuracy}%</Text>
            </View>
          ))
        )}

        <Text style={s.sectionTitle}>Weak areas — focus here first</Text>
        {weakAreas.length === 0 ? (
          <Text style={s.meta}>No weak areas flagged yet.</Text>
        ) : (
          weakAreas.slice(0, 12).map((w, i) => (
            <View key={i} style={s.row}>
              <Text>{w.topic}</Text>
              <Text>
                {w.accuracy}%  ·  {w.answered}q
              </Text>
            </View>
          ))
        )}
        <Footer branding={branding} />
      </Page>
    </Document>
  );
}

export function GeneratedExamPaperDoc({
  payload,
  branding,
  withAnswers = false,
}: {
  payload: {
    paper?: string | null;
    exam_body?: string | null;
    level?: string | null;
    assessment_year?: string | null;
    duration_minutes?: number | null;
    instructions: string[];
    total_marks: number;
    sections: { name: string; questions: Q[] }[];
  };
  branding?: PdfBranding | null;
  withAnswers?: boolean;
}) {
  const brand = resolvedPdfBranding(branding);
  const title = payload.paper || "Examination Paper";
  const meta = [
    payload.exam_body,
    payload.level,
    payload.assessment_year,
    payload.duration_minutes ? `${payload.duration_minutes} minutes` : null,
    `${payload.total_marks} marks`,
    withAnswers ? "ANSWER KEY" : null,
  ].filter(Boolean).join("   ·   ");
  return (
    <Document title={`${title}${withAnswers ? " — Answer key" : ""}`}>
      <Page size="A4" style={s.page}>
        <PaperHeader branding={branding} title={title} meta={meta} />
        {payload.instructions.length ? (
          <View style={{ marginBottom: 12 }}>
            <Text style={{ ...s.sectionTitle, color: brand.primary_color }}>Instructions</Text>
            {payload.instructions.map((instruction, index) => (
              <Text key={index} style={s.meta}>{index + 1}. {displayText(instruction)}</Text>
            ))}
          </View>
        ) : null}
        {payload.sections.map((section, sectionIndex) => (
          <View key={sectionIndex}>
            <Text style={{ ...s.sectionTitle, color: brand.primary_color }}>{section.name}</Text>
            {section.questions.map((question, index) => (
              <View key={question.number || index} style={s.qBlock} wrap={false}>
                <Text style={s.qText}>
                  {question.number || index + 1}. {displayText(question.question_text)} ({marksOf(question)} {marksOf(question) === 1 ? "mark" : "marks"})
                </Text>
                {question.options?.map((option, optionIndex) => (
                  <Text key={option.id || optionIndex} style={s.option}>
                    {LETTER[optionIndex] ?? optionIndex + 1}. {displayText(option.text)}
                  </Text>
                ))}
                {withAnswers ? (
                  <>
                    <Text style={{ ...s.answer, color: brand.primary_color }}>
                      Answer: {question.model_answer || answerText(question.correct_answer, question.options)}
                    </Text>
                    {question.explanation ? <Text style={s.explanation}>Why: {displayText(question.explanation)}</Text> : null}
                  </>
                ) : null}
              </View>
            ))}
          </View>
        ))}
        <Footer branding={branding} />
      </Page>
    </Document>
  );
}
