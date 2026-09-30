import {
  Document,
  Font,
  Image,
  Page,
  StyleSheet,
  Text,
  View,
} from "@react-pdf/renderer";

import type { HandwrittenEvaluationReport } from "@/lib/api";
import {
  buildHandwrittenReportView,
  formatEvaluationMark,
} from "@/lib/handwritten-report";
import {
  parseAnswerTranscript,
  type AnswerTranscriptBlock,
} from "@/lib/answer-transcript";
import { type PdfBranding, resolvedPdfBranding } from "./branding";

Font.register({
  family: "Noto Sans",
  fonts: [
    { src: "/fonts/NotoSans-Regular.ttf", fontWeight: 400 },
    { src: "/fonts/NotoSans-Bold.ttf", fontWeight: 700 },
  ],
});
Font.registerHyphenationCallback((word) => [word]);

const styles = StyleSheet.create({
  page: {
    paddingTop: 38,
    paddingBottom: 44,
    paddingHorizontal: 42,
    color: "#1E2932",
    fontFamily: "Noto Sans",
    fontSize: 9,
    lineHeight: 1.45,
  },
  header: { borderBottomWidth: 2, paddingBottom: 9, marginBottom: 16 },
  logo: { width: 100, height: 34, objectFit: "contain", marginBottom: 5 },
  brand: { fontSize: 8, fontWeight: 700, letterSpacing: 1.1 },
  title: { fontSize: 17, fontWeight: 700, marginTop: 3 },
  meta: { marginTop: 3, color: "#647480", fontSize: 8 },
  scoreHero: {
    flexDirection: "row",
    borderRadius: 7,
    marginBottom: 12,
    overflow: "hidden",
  },
  scoreBlock: { width: "34%", padding: 15, color: "#FFFFFF" },
  scoreLabel: { fontSize: 7, fontWeight: 700, letterSpacing: 0.9, opacity: 0.72 },
  scoreRow: { flexDirection: "row", alignItems: "flex-end", marginTop: 5 },
  score: { fontSize: 28, fontWeight: 700, lineHeight: 1 },
  scoreTotal: { marginLeft: 4, marginBottom: 3, fontSize: 10, opacity: 0.7 },
  scoreLevel: { marginTop: 7, fontSize: 8, fontWeight: 700 },
  summaryBlock: { width: "66%", padding: 15, backgroundColor: "#F7FAF8" },
  summary: { fontSize: 9.5, fontWeight: 700, lineHeight: 1.55 },
  metadata: { flexDirection: "row", borderWidth: 1, borderColor: "#D6E2DC", borderRadius: 5, marginBottom: 15 },
  metadataItem: { flexGrow: 1, width: "33.33%", padding: 8, borderRightWidth: 1, borderRightColor: "#D6E2DC" },
  metadataLast: { flexGrow: 1, width: "33.33%", padding: 8 },
  metadataLabel: { color: "#647480", fontSize: 6.5, fontWeight: 700, letterSpacing: 0.8 },
  metadataValue: { marginTop: 3, fontSize: 8.5, fontWeight: 700 },
  sectionEyebrow: { marginTop: 4, fontSize: 7, fontWeight: 700, letterSpacing: 0.9 },
  sectionTitle: { marginTop: 3, marginBottom: 7, fontSize: 13, fontWeight: 700 },
  table: { borderWidth: 1, borderColor: "#D6E2DC", borderRadius: 5, marginBottom: 13 },
  tableHead: { flexDirection: "row", padding: 7, backgroundColor: "#EFF8F3" },
  tableRow: { flexDirection: "row", padding: 7, borderTopWidth: 1, borderTopColor: "#E5ECE8" },
  colQuestion: { width: "55%", fontWeight: 700 },
  colScore: { width: "20%", textAlign: "center", fontWeight: 700 },
  colLevel: { width: "25%", textAlign: "right" },
  twoColumn: { flexDirection: "row", gap: 10, marginBottom: 14 },
  callout: { flexGrow: 1, width: "50%", borderWidth: 1, borderColor: "#D6E2DC", borderRadius: 5, padding: 9 },
  calloutTitle: { fontSize: 8, fontWeight: 700, marginBottom: 5 },
  bullet: { marginBottom: 3, color: "#41515B" },
  feedbackPage: { paddingTop: 61 },
  repeatHeader: {
    position: "absolute",
    top: 21,
    left: 42,
    right: 42,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderBottomWidth: 1.5,
    paddingBottom: 7,
  },
  repeatHeaderBrand: { fontSize: 7.5, fontWeight: 700, letterSpacing: 0.75 },
  repeatHeaderTitle: { color: "#647480", fontSize: 7 },
  feedbackIntro: { marginBottom: 10 },
  questionHeader: {
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1.5,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  questionHeaderText: { width: "85%" },
  questionLabel: { fontSize: 10.5, fontWeight: 700 },
  questionTitleCompact: { marginTop: 2, color: "#647480", fontSize: 8.1, lineHeight: 1.3 },
  questionScoreCompact: { width: "13%", textAlign: "right", fontSize: 9.5, fontWeight: 700 },
  questionLevel: { marginTop: 3, color: "#647480", fontSize: 7.2 },
  answerHeading: {
    marginTop: 7,
    marginBottom: 4,
    paddingVertical: 4,
    paddingHorizontal: 6,
    borderRadius: 3,
    fontSize: 7.2,
    fontWeight: 700,
    letterSpacing: 0.45,
  },
  answerParagraph: { marginBottom: 3.2, color: "#344650", fontSize: 8.25, lineHeight: 1.34 },
  transcriptHeading: { marginTop: 2, marginBottom: 2.5, fontSize: 8.4, fontWeight: 700 },
  transcriptList: { marginBottom: 3.2 },
  transcriptListLine: { marginBottom: 1.5, color: "#344650", fontSize: 8.25, lineHeight: 1.3 },
  transcriptWorking: { marginBottom: 3.5, padding: 5, backgroundColor: "#F5F8F7", borderRadius: 3 },
  transcriptWorkingLine: { marginBottom: 1.25, color: "#344650", fontSize: 8.1, lineHeight: 1.3 },
  transcriptVerdict: { marginBottom: 3.5, padding: 5, backgroundColor: "#F5F8F7", borderRadius: 3 },
  transcriptTable: { marginBottom: 4, borderWidth: 1, borderColor: "#D6E2DC" },
  transcriptTableRow: { flexDirection: "row", borderTopWidth: 1, borderTopColor: "#D6E2DC" },
  transcriptTableFirstRow: { flexDirection: "row", backgroundColor: "#EFF8F3" },
  transcriptTableCell: { flexGrow: 1, flexBasis: 0, padding: 3.5, borderRightWidth: 1, borderRightColor: "#D6E2DC", fontSize: 7.7, lineHeight: 1.25 },
  compactSection: { marginTop: 6, padding: 6, borderRadius: 3, backgroundColor: "#F5F8F7" },
  compactSectionTitle: { marginBottom: 3, fontSize: 7.2, fontWeight: 700, letterSpacing: 0.4 },
  compactText: { color: "#344650", fontSize: 8.15, lineHeight: 1.35 },
  pair: { marginTop: 3, paddingTop: 3, borderTopWidth: 1, borderTopColor: "#E8DDBE" },
  footer: { position: "absolute", bottom: 22, left: 42, right: 42, flexDirection: "row", justifyContent: "space-between", color: "#8A9790", fontSize: 7 },
});

function formattedDate(value: string): string {
  return new Date(value).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function TranscriptBlock({
  block,
  brandColor,
}: {
  block: AnswerTranscriptBlock;
  brandColor: string;
}) {
  if (block.type === "table") {
    const width = Math.max(...block.rows.map((row) => row.length));
    return (
      <View style={styles.transcriptTable}>
        {block.rows.map((row, rowIndex) => (
          <View
            key={`${rowIndex}-${row.join("-")}`}
            style={rowIndex === 0 ? styles.transcriptTableFirstRow : styles.transcriptTableRow}
            wrap={false}
          >
            {Array.from({ length: width }, (_, cellIndex) => (
              <Text
                key={cellIndex}
                style={{
                  ...styles.transcriptTableCell,
                  ...(cellIndex === width - 1 ? { borderRightWidth: 0 } : {}),
                  ...(rowIndex === 0 ? { fontWeight: 700 } : {}),
                }}
              >
                {row[cellIndex] || " "}
              </Text>
            ))}
          </View>
        ))}
      </View>
    );
  }

  if (block.type === "heading") {
    return <Text style={{ ...styles.transcriptHeading, color: brandColor }}>{block.text}</Text>;
  }

  if (block.type === "working" || block.type === "list") {
    return (
      <View style={block.type === "working" ? styles.transcriptWorking : styles.transcriptList}>
        {block.lines.map((line, index) => (
          <Text
            key={`${index}-${line}`}
            style={block.type === "working" ? styles.transcriptWorkingLine : styles.transcriptListLine}
          >
            {line}
          </Text>
        ))}
      </View>
    );
  }

  if (block.type === "verdict") {
    return (
      <View style={styles.transcriptVerdict} wrap={false}>
        <Text style={{ ...styles.compactText, fontWeight: 700, color: brandColor }}>
          {[block.prefix, block.verdict].filter(Boolean).join(" ")}
        </Text>
        {block.explanation ? <Text style={styles.compactText}>{block.explanation}</Text> : null}
      </View>
    );
  }

  if (block.type === "text") {
    return <Text style={styles.answerParagraph}>{block.text}</Text>;
  }

  return null;
}

function AnswerTranscript({ text, brandColor }: { text: string; brandColor: string }) {
  const blocks = parseAnswerTranscript(text);
  if (!blocks.length) {
    return <Text style={styles.answerParagraph}>No answer text was extracted.</Text>;
  }
  return (
    <>
      {blocks.map((block, index) => (
        <TranscriptBlock key={`${block.type}-${index}`} block={block} brandColor={brandColor} />
      ))}
    </>
  );
}

export function HandwrittenEvaluationReportDoc({
  report,
  branding,
}: {
  report: HandwrittenEvaluationReport;
  branding?: PdfBranding | null;
}) {
  const brand = resolvedPdfBranding(branding);
  const view = buildHandwrittenReportView(report);
  const studentName = report.student.name || report.student.email || "Student";

  return (
    <Document title={`${report.paper.title} — Evaluation Summary`} author={brand.name}>
      <Page size="A4" style={styles.page}>
        <View style={{ ...styles.header, borderBottomColor: brand.primary_color }}>
          {brand.logo_url ? (
            // React PDF's Image is not a DOM image and has no alt prop.
            // eslint-disable-next-line jsx-a11y/alt-text
            <Image src={brand.logo_url} style={styles.logo} />
          ) : null}
          <Text style={{ ...styles.brand, color: brand.primary_color }}>{brand.name.toUpperCase()}</Text>
          <Text style={styles.title}>Student Evaluation Summary</Text>
          <Text style={styles.meta}>{report.paper.title}</Text>
        </View>

        <View style={styles.scoreHero}>
          <View style={{ ...styles.scoreBlock, backgroundColor: brand.primary_color }}>
            <Text style={styles.scoreLabel}>OVERALL PERFORMANCE</Text>
            <View style={styles.scoreRow}>
              <Text style={styles.score}>{formatEvaluationMark(view.score)}</Text>
              <Text style={styles.scoreTotal}>/ {formatEvaluationMark(view.total)}</Text>
            </View>
            <Text style={styles.scoreLevel}>{view.level.percentage}%  ·  {view.level.label}</Text>
          </View>
          <View style={styles.summaryBlock}>
            <Text style={styles.summary}>{view.summary}</Text>
            <Text style={styles.meta}>Focused feedback for the next attempt</Text>
          </View>
        </View>

        <View style={styles.metadata}>
          <View style={styles.metadataItem}>
            <Text style={styles.metadataLabel}>PAPER</Text>
            <Text style={styles.metadataValue}>{report.paper.title}</Text>
          </View>
          <View style={styles.metadataItem}>
            <Text style={styles.metadataLabel}>STUDENT</Text>
            <Text style={styles.metadataValue}>{studentName}</Text>
          </View>
          <View style={styles.metadataLast}>
            <Text style={styles.metadataLabel}>EVALUATED</Text>
            <Text style={styles.metadataValue}>{formattedDate(report.evaluation_date)}</Text>
          </View>
        </View>

        <Text style={{ ...styles.sectionEyebrow, color: brand.primary_color }}>AT A GLANCE</Text>
        <Text style={styles.sectionTitle}>Question Performance</Text>
        <View style={styles.table}>
          <View style={styles.tableHead}>
            <Text style={styles.colQuestion}>Question</Text>
            <Text style={styles.colScore}>Score</Text>
            <Text style={styles.colLevel}>Current level</Text>
          </View>
          {view.guidance.map((item) => (
            <View key={item.label} style={styles.tableRow}>
              <Text style={styles.colQuestion}>{item.label}</Text>
              <Text style={styles.colScore}>{item.scoreLabel}</Text>
              <Text style={styles.colLevel}>{item.level.label}</Text>
            </View>
          ))}
        </View>

        <View style={styles.twoColumn}>
          <View style={styles.callout}>
            <Text style={{ ...styles.calloutTitle, color: brand.primary_color }}>YOUR STRENGTHS</Text>
            {(view.strengths.length ? view.strengths : ["Keep building on the points that earned credit."]).map((item) => (
              <Text key={item} style={styles.bullet}>• {item}</Text>
            ))}
          </View>
          <View style={styles.callout}>
            <Text style={{ ...styles.calloutTitle, color: brand.primary_color }}>YOUR NEXT THREE STEPS</Text>
            {view.nextSteps.map((item, index) => (
              <Text key={item} style={styles.bullet}>{index + 1}. {item}</Text>
            ))}
          </View>
        </View>

        <View style={styles.footer} fixed>
          <Text>{brand.name}  ·  Personalised Evaluation Summary</Text>
          <Text render={({ pageNumber, totalPages }) => `Page ${pageNumber} of ${totalPages}`} />
        </View>
      </Page>
      {view.guidance.map((item, itemIndex) => (
        <Page key={`${item.label}-${itemIndex}`} size="A4" style={[styles.page, styles.feedbackPage]} wrap>
          <View
            style={{ ...styles.repeatHeader, borderBottomColor: brand.primary_color }}
            fixed
          >
            <Text style={{ ...styles.repeatHeaderBrand, color: brand.primary_color }}>
              {brand.name.toUpperCase()}
            </Text>
            <Text style={styles.repeatHeaderTitle}>{report.paper.title}  ·  Student Evaluation Summary</Text>
          </View>

          {itemIndex === 0 ? (
            <View style={styles.feedbackIntro} wrap={false}>
              <Text style={{ ...styles.sectionEyebrow, color: brand.primary_color }}>FOCUSED FEEDBACK</Text>
              <Text style={styles.sectionTitle}>Question-by-Question Guidance</Text>
              <Text style={styles.meta}>Review what earned credit and what to improve on the next attempt.</Text>
            </View>
          ) : null}

            <View
              style={{ ...styles.questionHeader, borderTopColor: brand.primary_color }}
            >
              <View style={styles.questionHeaderText}>
                <Text style={styles.questionLabel}>{item.label}</Text>
                {item.title ? <Text style={styles.questionTitleCompact}>{item.title}</Text> : null}
                <Text style={styles.questionLevel}>{item.level.label}</Text>
              </View>
              <Text style={{ ...styles.questionScoreCompact, color: brand.primary_color }}>{item.scoreLabel}</Text>
            </View>

            {item.statusDescription ? <Text style={styles.answerParagraph}>{item.statusDescription}</Text> : null}

            <Text
              style={{
                ...styles.answerHeading,
                color: brand.primary_color,
                backgroundColor: `${brand.primary_color}12`,
              }}
              wrap={false}
            >
              WHAT YOU WROTE
            </Text>
            <AnswerTranscript text={item.studentAnswer} brandColor={brand.primary_color} />

            <View style={styles.compactSection}>
              <Text style={{ ...styles.compactSectionTitle, color: brand.primary_color }}>WHAT YOU DID WELL</Text>
              <Text style={styles.compactText}>{item.didWell}</Text>
            </View>

            {item.mistakes.length ? (
              <View style={{ ...styles.compactSection, backgroundColor: "#FFF8E8" }}>
                <Text style={styles.compactSectionTitle}>MISTAKES &amp; EXPECTED ANSWERS</Text>
                {item.mistakes.map((pair, index) => (
                  <View key={`${pair.mistake}-${index}`} style={index ? styles.pair : undefined} wrap={false}>
                    <Text style={styles.compactText}>Mistake: {pair.mistake}</Text>
                    <Text style={styles.compactText}>Expected: {pair.expected}</Text>
                  </View>
                ))}
              </View>
            ) : item.expectedPoints.length ? (
              <View style={styles.compactSection}>
                <Text style={styles.compactSectionTitle}>EXPECTED ANSWER POINTS</Text>
                {item.expectedPoints.map((point) => <Text key={point} style={styles.compactText}>• {point}</Text>)}
              </View>
            ) : null}
          <View style={styles.footer} fixed>
            <Text>{brand.name}  ·  {studentName}</Text>
            <Text render={({ pageNumber, totalPages }) => `Page ${pageNumber} of ${totalPages}`} />
          </View>
        </Page>
      ))}
    </Document>
  );
}
