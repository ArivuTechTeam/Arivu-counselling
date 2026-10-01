import { HandwrittenReport } from "@/components/student/handwritten-report";

export default async function TeacherHandwrittenReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <HandwrittenReport
      submissionId={id}
      backHref="/dashboard/teacher/handwritten-evaluation"
    />
  );
}
