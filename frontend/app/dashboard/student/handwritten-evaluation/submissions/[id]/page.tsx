import { HandwrittenReport } from "@/components/student/handwritten-report";

export default async function HandwrittenReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <HandwrittenReport submissionId={id} />;
}
