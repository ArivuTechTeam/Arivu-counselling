import { ClassAnalytics } from "@/components/teacher/class-analytics";
import { TeacherStats } from "@/components/teacher/teacher-stats";

// Class overview — the teacher's at-a-glance workspace + class performance.
export default function TeacherClassOverview() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <TeacherStats />
      <ClassAnalytics />
    </div>
  );
}
